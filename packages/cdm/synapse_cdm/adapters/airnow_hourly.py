"""`airnow_hourly`, #28 in the ordinal table: one EPA AirNow hourly observation file -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One of AirNow's two hourly observation files (DECISIONS L-20), told apart by their shape:

- `HourlyData_yyyymmddhh.dat`: no header line, `|`-delimited, nine fields a line — valid date
  (`mm/dd/yy`, a two-digit year), valid time, AQSID, site name, GMT offset, parameter name,
  reporting units, value, data source — one parameter of one site a line;
- `HourlyAQObs_yyyymmddhh.dat`: a quoted CSV with a 34-name header line, one site a line, its
  position, its NowCast AQI per pollutant and its raw concentrations each beside its unit. The
  header is compared whole with the names as the files write them: the fact sheet's field list
  spells one of them `Ozone_Measured` where the files write `OZONE_Measured`, and a header with
  the fact sheet's spelling is refused.

`to_cdm` takes the file's octets or its parsed twin (`<name>.parsed.json`: `form`, the header
where there is one, and every field of every line as written). The two layouts are read from
AirNow's fact sheets for the two files, pinned by SHA-256 in
`fixtures/airnow_hourly/spec/airnow_hourly_pin.json` and not carried.

TIME
----
Both files are stamped in GMT, and a stamp marks the BEGINNING of a one-hour measurement period:
"a data value with a time of 17:00 represents a sample measured from 17:00 to 17:59 GMT"
(research-station-text F08). So a record's `validity.effective` is [start, start + 1 h] and its
`observed_at` is the hour's END (design-judge DJ-04: an observation's `observed_at` is the end of
its sensing interval); `SourceRef.observed_at` keeps the stamp the record states, the start. The
GMT offset the files carry converts to local STANDARD time and is never applied: nothing here is
local. A two-digit year is 20YY — AirNow's hourly files begin in 2019 — and a stamp whose minutes
are not `00` is refused, because it would name no hour.

WHAT ONE FILE BECOMES
---------------------
One `ENVIRONMENTAL_OBSERVATION` Event per line, in file order, each carrying the
`point-observation/1` contract: a HourlyData line's one parameter, or a HourlyAQObs line's AQIs
and concentrations; then one `Entity` (SENSOR, `site_entity`) per site, in the order sites first
appear. Parameter names and units are carried verbatim and the vocabulary is open (F09: the files
name parameters and units the fact sheets do not list), and a negative raw concentration is a
value, never clamped (F09). Only valid data are reported in these files, so a missing value is a
line that is not there (HourlyData) or a blank field (HourlyAQObs), never a sentinel; a blank
concentration states no reading, and a concentration with a blank unit is an absence of cause
`unit_unknown` whose number stays in the residual. HourlyData states no position: it comes from
the caller's site table (an AirNow `monitoring_site_locations.dat` reading, F19), else `None`.
AirNow publishes no per-value quality flag, so each contract states that absence with its basis.
The files are rewritten for 48 and 72 hours after the hour, so a file name is not an identity:
the host's digest of the bytes is (gap-host-manifest HM-07).
"""

from __future__ import annotations

import csv
import datetime as _dt
import re
from typing import Any

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
    OperationalStatus,
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
    Reading,
    StationTable,
    TableLocator,
    TimeInputs,
    TimeSystem,
    decimal_float,
    observation_event,
    site_entity,
    text_lines,
    twin_text,
)

#: `source.system` on every object and the system of every identifier.
SYSTEM = "AirNow"
FORMAT_NAME = "EPA AirNow hourly observation files (HourlyData, HourlyAQObs)"
FORMAT_VERSION = (
    "AirNow Hourly Data File fact sheet (last updated August 2025) and Hourly AQ Obs File fact "
    "sheet (updated March 2023)"
)
HOURLY_DATA = "HourlyData"
HOURLY_AQOBS = "HourlyAQObs"

#: DECISIONS U-07: station text, one file of at most 8 MiB.
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 64

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_airnow_hourly_adapter.py::"

#: The HourlyData fields, in the fact sheet's order; the file states them in no header.
HOURLY_DATA_FIELDS = (
    "Valid date",
    "valid time",
    "AQSID",
    "sitename",
    "GMT offset",
    "parameter name",
    "reporting units",
    "value",
    "data source",
)

#: The HourlyAQObs header, the 34 names in the file's order (the Hourly AQ Obs fact sheet), as
#: the files write them. The fact sheet's own field list spells the 19th `Ozone_Measured`, the one
#: name of its list not in the case the other pollutants' names take; the files write
#: `OZONE_Measured`, and this closed header holds the files' spelling, so a header with the fact
#: sheet's is refused `unknown-header` rather than read.
HOURLY_AQOBS_FIELDS = (
    "AQSID",
    "SiteName",
    "Status",
    "EPARegion",
    "Latitude",
    "Longitude",
    "Elevation",
    "GMTOffset",
    "CountryCode",
    "StateName",
    "ValidDate",
    "ValidTime",
    "DataSource",
    "ReportingArea_PipeDelimited",
    "OZONE_AQI",
    "PM10_AQI",
    "PM25_AQI",
    "NO2_AQI",
    "OZONE_Measured",
    "PM10_Measured",
    "PM25_Measured",
    "NO2_Measured",
    "PM25",
    "PM25_Unit",
    "OZONE",
    "OZONE_Unit",
    "NO2",
    "NO2_Unit",
    "CO",
    "CO_Unit",
    "SO2",
    "SO2_Unit",
    "PM10",
    "PM10_Unit",
)
_AQ = {name: index for index, name in enumerate(HOURLY_AQOBS_FIELDS)}

#: The fields of a line that describe its site rather than its value, by form.
SITE_FIELDS = {
    HOURLY_DATA: ("AQSID", "sitename", "GMT offset", "data source"),
    HOURLY_AQOBS: (
        "AQSID",
        "SiteName",
        "Status",
        "EPARegion",
        "Latitude",
        "Longitude",
        "Elevation",
        "GMTOffset",
        "CountryCode",
        "StateName",
        "DataSource",
        "ReportingArea_PipeDelimited",
    ),
}

#: The four indices a HourlyAQObs line states, in the file's order.
AQI_FIELDS = ("OZONE_AQI", "PM10_AQI", "PM25_AQI", "NO2_AQI")
#: The six raw concentrations, each with the field that states its unit, in the file's order.
CONCENTRATIONS = ("PM25", "OZONE", "NO2", "CO", "SO2", "PM10")
MEASURED_FIELDS = ("OZONE_Measured", "PM10_Measured", "PM25_Measured", "NO2_Measured")

#: An AQS site identifier: nine or twelve characters (the Hourly AQ Obs fact sheet: twelve for a
#: site created after June 2018, three country digits before the nine). The fact sheets call it
#: numeric and their own sample records state one with letters, so letters and digits are read.
_AQSID = re.compile(r"[0-9A-Z]{9}|[0-9A-Z]{12}")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_DATE_YY = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{2})")
_DATE_YYYY = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_HOUR = re.compile(r"([0-9]{2}):00")
_TIME = re.compile(r"[0-9]{2}:[0-9]{2}")

TIME_SYSTEM = TimeSystem(
    name="GMT",
    stated_by="source",
    basis=(
        "the AirNow fact sheets: the valid date and valid time are GMT and mark the beginning of "
        "a one-hour measurement period (research-station-text F08)"
    ),
)
QUALITY_FLAGS_BASIS = (
    "AirNow's hourly files carry no per-value quality flag: only valid data are reported, a "
    "missing value is a line or a field that is not there, and every value is preliminary (the "
    "Hourly Data and Hourly AQ Obs fact sheets; research-station-text F08, F09). HourlyAQObs's "
    "*_Measured fields say whether a site measures a pollutant and stay in the residual."
)
UNIT_UNKNOWN = (
    "the line states the concentration and leaves its unit field blank, so the value's unit is "
    "not stated and the number stays in the Event's residual"
)
AQI_UNIT_NAMESPACE = (
    "the Hourly AQ Obs fact sheet: the field is the NowCast Air Quality Index (NO2's the hourly "
    "AQI), an index of 0 to 500 with no other unit"
)

T_HOUR = (
    "the valid date and time are read as the GMT start of a one-hour period; observed_at is its "
    "end, one hour later"
)
T_TWO_DIGIT_YEAR = "a two-digit year is read as 20YY: AirNow's hourly files begin in 2019"
T_NUMBER = "each value's decimal text is read as a binary floating-point number"

FIXTURE_SITES = StationTable(
    name="airnow-hourly-fixture-sites",
    basis="synthetic site positions written for the packaged fixtures on 2026-10-15 "
    "(fixtures/airnow_hourly/README.md); no real site is named",
    rows=[
        {"station_id": "000000001", "lat": 56.95, "lon": 24.1},
        {"station_id": "000000002", "lat": 57.4, "lon": 21.6},
        {"station_id": "000000000011", "lat": 56.5, "lon": 21.0},
    ],
)


class AirnowRefused(ValueError):
    """A file this module will not translate. `code` names the rule; the text names the line or
    the field, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> AirnowRefused:
    refusal = AirnowRefused(code, "")
    refusal.args = (message,)
    return refusal


# -- octets to the twin --------------------------------------------------------------------------


def parse_file(octets: bytes) -> dict:
    """The file's lines as its twin, the form told by the first line: a quoted `"AQSID"` opens a
    HourlyAQObs file, and a line with `|` is a HourlyData line."""
    lines, _ = text_lines(octets, AirnowRefused)
    if lines[0].startswith('"AQSID"'):
        fields = []
        for number, line in enumerate(lines, start=1):
            try:
                fields.append(next(csv.reader([line], strict=True)))
            except csv.Error:
                raise AirnowRefused(
                    "bad-csv-line", f"line {number} is not one CSV record"
                ) from None
        return {"form": HOURLY_AQOBS, "header": fields[0], "rows": fields[1:]}
    if "|" in lines[0]:
        return {"form": HOURLY_DATA, "records": [line.split("|") for line in lines]}
    raise AirnowRefused(
        "unknown-form", "line 1 is neither the HourlyAQObs header nor a HourlyData line"
    )


def _fields(value: Any, where: str) -> list[str]:
    if not isinstance(value, list):
        raise AirnowRefused("not-a-twin", f"{where} is not a list of fields")
    for index, field in enumerate(value):
        if not twin_text(field) and field != "":
            raise AirnowRefused("not-a-twin", f"{where}[{index}] is not a field a file could hold")
    return value


def _check_twin(document: dict) -> dict:
    form = document.get("form")
    if form == HOURLY_DATA and set(document) == {"form", "records"}:
        lines = document["records"]
        key = "records"
    elif form == HOURLY_AQOBS and set(document) == {"form", "header", "rows"}:
        _fields(document["header"], "header")
        lines = document["rows"]
        key = "rows"
    else:
        raise AirnowRefused(
            "not-a-twin",
            "a twin is {form: HourlyData, records} or {form: HourlyAQObs, header, rows}",
        )
    if not isinstance(lines, list):
        raise AirnowRefused("not-a-twin", f"{key} is not a list")
    for index, line in enumerate(lines):
        _fields(line, f"{key}[{index}]")
    return document


# -- the declaration -----------------------------------------------------------------------------


class AirnowHourlyAdapter(Adapter):
    """One AirNow hourly file in; one Event per line and one Entity per site out."""

    name = "airnow_hourly"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: `PUBLIC_GOVERNMENT` (DECISIONS L-10): a US Government agency's free public download. The
    #: AirNow Data Exchange Guidelines are conduct terms on data the reporting agencies own —
    #: credit the agencies, say the data are preliminary, disseminate them as received
    #: (research-station-text F10) — and the pin record states them beside the class.
    metadata = AdapterMetadata(
        id="airnow_hourly",
        name="EPA AirNow hourly observation file (HourlyData, HourlyAQObs) translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter airnow_hourly` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every line a structured residual on its own Event) with no LOST leaf on any parsed "
            "twin. L4 is NOT declared: this adapter is ingest-only, so the roundtrip check is "
            "inapplicable rather than passed (ARCHITECTURE.md §3.6, rule 4), and a rung passed "
            "vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "EPA AirNow HourlyData_yyyymmddhh.dat (header-less, |-delimited) or "
                "HourlyAQObs_yyyymmddhh.dat (quoted CSV), one file per call, as its octets or "
                "its parsed twin; one ENVIRONMENTAL_OBSERVATION Event per line carrying "
                "point-observation/1, and one Entity per site",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "not a bound of its own: one Event per line and at most one "
                    "Entity per line, and a line is at least 34 octets (the date, the time, a "
                    "nine-character AQSID, a value and the delimiters), so max_input_bytes "
                    "bounds the count",
                    "max_decompressed_bytes": "this adapter inflates nothing: a compressed "
                    "file is unwrapped by synapse-decode --container gzip under the host's own "
                    "bounds before the adapter is handed it",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, and every pass over the file is one walk of its lines and fields; "
                    "the conformance suite's parser worker kills a decode that overruns its "
                    "deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "No AirNow document states a maximum size for an hourly file. The "
                            "design record's figure is one HourlyData file of 7878 lines for "
                            "one hour, every publicly approved site in AirNow "
                            "(research-station-text F08), and a HourlyAQObs file is one line a "
                            "site. DECISIONS U-07 rules one station-text file at most 8 MiB "
                            "(8 388 608 octets, `MAX_INPUT_BYTES`, `adapters/airnow_hourly.py`), "
                            "with the CO-OPS request range limits (research-station-text F05) "
                            "the class's other stated unit. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module decodes a line"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets are never JSON; the parsed twin nests three containers "
                            "(the twin, its lines, a line). 64 (`MAX_DEPTH`, "
                            "`adapters/airnow_hourly.py`) is the harness loader's own bound and "
                            "the figure the JSON-reading adapters of synapse_cdm declare. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on a dict before this class's "
                            "`to_cdm` runs"
                        ),
                        test=_TESTS + "test_a_twin_past_the_depth_bound_is_refused_before_decode",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "a HourlyData line is exactly the fact sheet's nine fields and a HourlyAQObs "
                "header exactly the 34 names the files write (OZONE_Measured where the fact "
                "sheet's list spells Ozone_Measured), so a field this module does not know is refused "
                "rather than carried; the twin's keys are closed and an injected key is refused "
                "`not-a-twin`"
            ),
        ),
        limitations=[
            Limitation(
                id="hourly-files-only",
                summary="HourlyData and HourlyAQObs files are read; the forecast file "
                "(reportingarea.dat), the site file (monitoring_site_locations.dat), the API's "
                "responses and EPA AQS records are not, and nothing is joined from another file",
            ),
            Limitation(
                id="site-position-from-the-caller",
                summary="a HourlyData line states no position: it comes only from a caller's "
                "site table (a StationTable keyed by AQSID), else the site Entity's position is "
                "null; a HourlyAQObs line's Latitude and Longitude are its stated position, and "
                "its Elevation, whose datum the fact sheet does not state, stays in the residual",
            ),
            Limitation(
                id="hour-start-stamps",
                summary="a stamp is the GMT start of a one-hour period: validity.effective is "
                "[start, start + 1 h] and observed_at its end; the GMT offset (to local "
                "standard time) is never applied",
            ),
            Limitation(
                id="aqi-unit",
                summary="a HourlyAQObs AQI field is carried with the unit AQI under the fact "
                "sheet's definition, an index with no other unit; a concentration's unit is "
                "its own *_Unit field, verbatim",
            ),
            Limitation(
                id="no-empty-lines",
                summary="a HourlyAQObs line stating neither an AQI nor a concentration is "
                "refused no-reading, and a HourlyData line with a blank value or unit is "
                "refused blank-value: the fact sheets say only valid data are reported, and the "
                "design record holds no such line",
            ),
            Limitation(
                id="no-quality-flags",
                summary="AirNow's hourly files carry no per-value quality flag, so every "
                "contract states quality_flags_basis; the data are preliminary, and the "
                "AirNow Data Exchange Guidelines' terms bind the consumer, not this package",
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

    #: The ledger. Each Event's residual holds its own line as written, and the Events come
    #: first in line order with the site Entities after them, so line i is bound to object i; a
    #: line's AQSID is also held to its contract's station, and a HourlyData line's value to its
    #: one reading.
    MAPPINGS = {
        "records[*][2]": (
            Mapping(to="#[*]:residual.data.record[2]", kind="residual"),
            Mapping(to="#[*]:payload.observation.station_id"),
        ),
        "records[*][7]": (
            Mapping(to="#[*]:residual.data.record[7]", kind="residual"),
            Mapping(
                to="#[*]:payload.observation.readings[0].measurement.value",
                rule="numeric_text",
            ),
        ),
        "records[*]": Mapping(to="#[*]:residual.data.record", kind="residual"),
        "rows[*][0]": (
            Mapping(to="#[*]:residual.data.row[0]", kind="residual"),
            Mapping(to="#[*]:payload.observation.station_id"),
        ),
        "rows[*]": Mapping(to="#[*]:residual.data.row", kind="residual"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        site_table: StationTable | None = None,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
    ) -> None:
        """`site_table` supplies the positions a HourlyData file does not state, keyed by AQSID.
        `source_hash` is the SHA-256 of the file as the host read it and `frame_sha256` that of
        what it handed over when that is not the file. All are constructor arguments, so all are
        in the determinism tuple."""
        super().__init__(clock, synthetic=synthetic)
        if site_table is not None and not isinstance(site_table, StationTable):
            raise ValueError("site_table is a StationTable")
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
        self._site_table = site_table
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The packaged fixtures' context: the synthetic site table of three sites. It is the
        context of those fixtures only (`Adapter.fixture_instance`)."""
        return cls(clock=clock, synthetic=synthetic, site_table=FIXTURE_SITES)

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One file -> [one Event per line, in file order, then one Entity per site]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            twin = parse_file(bytes(raw))
        elif isinstance(raw, dict):
            twin = _check_twin(raw)
        else:
            raise AirnowRefused(
                "unsupported-input",
                "a file is handed over as its octets or as its twin in a dict; text and other "
                "types are not taken",
            )
        if twin["form"] == HOURLY_DATA:
            records = [self._hourly_data(line, index) for index, line in enumerate(twin["records"])]
        else:
            if tuple(twin["header"]) != HOURLY_AQOBS_FIELDS:
                raise AirnowRefused(
                    "unknown-header", "the HourlyAQObs header is not the 34 names the files write"
                )
            records = [
                self._hourly_aqobs(line, index, twin["header"])
                for index, line in enumerate(twin["rows"])
            ]
        if not records:
            raise AirnowRefused("no-data-line", "the file holds no data line")
        return self._objects(twin["form"], records)

    # -- the two forms ---------------------------------------------------------------------------

    def _hourly_data(self, line: list[str], index: int) -> dict:
        where = f"record {index}"
        if len(line) != len(HOURLY_DATA_FIELDS):
            raise AirnowRefused("width-mismatch", f"{where} does not hold the nine fields")
        start, two_digit = self._start(line[0], line[1], where, two_digit_year=True)
        aqsid = self._aqsid(line[2], where)
        if _NUMBER.fullmatch(line[4]) is None:
            raise AirnowRefused("not-a-number", f"{where}: the GMT offset is not a number")
        parameter, unit, value = line[5], line[6], line[7]
        for name, text in (
            ("parameter name", parameter),
            ("reporting units", unit),
            ("value", value),
        ):
            if not text.strip():
                raise AirnowRefused("blank-value", f"{where}: the {name} is blank")
        reading = Reading(
            name=parameter,
            namespace="AirNow HourlyData parameter name",
            measurement=Measurement(
                value=self._number(value, f"{where}: the value"),
                unit=unit,
                unit_namespace="AirNow HourlyData reporting units field",
            ),
        )
        return {
            "index": index,
            "aqsid": aqsid,
            "start": start,
            "two_digit": two_digit,
            "readings": [reading],
            "external": f"{aqsid}/{parameter}/{times.render(start)}",
            "residual": {"form": HOURLY_DATA, "record": list(line)},
            "stated": None,
            "status": None,
            "site": dict(zip(SITE_FIELDS[HOURLY_DATA], (line[2], line[3], line[4], line[8]))),
        }

    def _hourly_aqobs(self, line: list[str], index: int, header: list[str]) -> dict:
        where = f"row {index}"
        if len(line) != len(HOURLY_AQOBS_FIELDS):
            raise AirnowRefused("width-mismatch", f"{where} does not hold the 34 fields")
        value = dict(zip(HOURLY_AQOBS_FIELDS, line))
        aqsid = self._aqsid(value["AQSID"], where)
        date = value["ValidDate"]
        start, two_digit = self._start(
            date, value["ValidTime"], where, two_digit_year=_DATE_YY.fullmatch(date) is not None
        )
        lat, lon = value["Latitude"], value["Longitude"]
        if bool(lat.strip()) != bool(lon.strip()):
            raise AirnowRefused("bad-position", f"{where} states one of Latitude and Longitude")
        stated = None
        if lat.strip():
            stated = (
                self._coordinate(lat, f"{where}: Latitude", 90.0),
                self._coordinate(lon, f"{where}: Longitude", 180.0),
            )
        for name in ("Elevation", "GMTOffset"):
            if value[name].strip() and _NUMBER.fullmatch(value[name]) is None:
                raise AirnowRefused("not-a-number", f"{where}: {name} is not a number")
        for name in MEASURED_FIELDS:
            if value[name] not in ("0", "1"):
                raise AirnowRefused("bad-measured-flag", f"{where}: {name} is not 0 or 1")
        readings = []
        for name in AQI_FIELDS:
            if value[name].strip():
                readings.append(
                    Reading(
                        name=name,
                        namespace="AirNow HourlyAQObs field",
                        measurement=Measurement(
                            value=self._number(value[name], f"{where}: {name}"),
                            unit="AQI",
                            unit_namespace=AQI_UNIT_NAMESPACE,
                        ),
                    )
                )
        for name in CONCENTRATIONS:
            text, unit = value[name], value[f"{name}_Unit"]
            if not text.strip():
                continue
            number = self._number(text, f"{where}: {name}")
            if unit.strip():
                readings.append(
                    Reading(
                        name=name,
                        namespace="AirNow HourlyAQObs field",
                        measurement=Measurement(
                            value=number,
                            unit=unit,
                            unit_namespace=f"AirNow HourlyAQObs {name}_Unit field",
                        ),
                    )
                )
            else:
                readings.append(
                    Reading(
                        name=name,
                        namespace="AirNow HourlyAQObs field",
                        absence=Absence(cause="unit_unknown", mechanism=UNIT_UNKNOWN),
                    )
                )
        if not readings:
            raise AirnowRefused("no-reading", f"{where} states no AQI and no concentration")
        status = value["Status"].strip() and OperationalStatus(
            state=value["Status"], namespace="AirNow HourlyAQObs Status"
        )
        return {
            "index": index,
            "aqsid": aqsid,
            "start": start,
            "two_digit": two_digit,
            "readings": readings,
            "external": f"{aqsid}/{times.render(start)}",
            "residual": {"form": HOURLY_AQOBS, "header": list(header), "row": list(line)},
            "stated": stated,
            "status": status or None,
            "site": {name: value[name] for name in SITE_FIELDS[HOURLY_AQOBS]},
        }

    # -- the pieces ------------------------------------------------------------------------------

    @staticmethod
    def _aqsid(text: str, where: str) -> str:
        if _AQSID.fullmatch(text) is None:
            raise AirnowRefused(
                "bad-aqsid", f"{where}: the AQSID is not nine or twelve letters and digits"
            )
        return text

    @staticmethod
    def _number(text: str, where: str) -> float:
        if _NUMBER.fullmatch(text) is None:
            raise AirnowRefused("not-a-number", f"{where} is not a decimal number")
        value = decimal_float(text)
        if value is None:
            raise AirnowRefused(
                "number-out-of-range", f"{where} lies outside what a binary double holds"
            )
        return value

    @staticmethod
    def _coordinate(text: str, where: str, bound: float) -> float:
        value = decimal_float(text) if _NUMBER.fullmatch(text) is not None else None
        if value is None or not -bound <= value <= bound:
            raise AirnowRefused(
                "bad-position", f"{where} is not decimal degrees within +/-{bound:g}"
            )
        return value

    @staticmethod
    def _start(
        date: str, time: str, where: str, *, two_digit_year: bool
    ) -> tuple[_dt.datetime, bool]:
        match = (_DATE_YY if two_digit_year else _DATE_YYYY).fullmatch(date)
        if match is None:
            raise AirnowRefused(
                "bad-date",
                f"{where}: the valid date is not mm/dd/yy"
                + ("" if two_digit_year else " or mm/dd/yyyy"),
            )
        month, day, year = (int(g) for g in match.groups())
        if two_digit_year:
            year += 2000
        if _TIME.fullmatch(time) is None:
            raise AirnowRefused("bad-time", f"{where}: the valid time is not hh:mm")
        hour = _HOUR.fullmatch(time)
        if hour is None:
            raise AirnowRefused("not-an-hour", f"{where}: the valid time is not on the hour")
        try:
            start = _dt.datetime(year, month, day, int(hour.group(1)), tzinfo=_dt.timezone.utc)
        except ValueError:
            raise AirnowRefused(
                "bad-date", f"{where}: the valid date and time name no hour"
            ) from None
        if start.year == 9999 and start.month == 12 and start.day == 31 and start.hour == 23:
            raise AirnowRefused("bad-date", f"{where}: the hour ends after 9999-12-31")
        return start, two_digit_year

    def _objects(self, form: str, records: list[dict]) -> list[CDMBase]:
        stamp_base = self.source_ref().model_copy(update={"source_hash": self._source_hash})
        seen: dict[str, int] = {}
        sites: dict[str, dict] = {}
        for record in records:
            key = record["external"]
            if key in seen:
                raise AirnowRefused(
                    "repeated-record",
                    f"record {record['index']} states the site, parameter and hour of record "
                    f"{seen[key]}",
                )
            seen[key] = record["index"]
            end = record["start"] + _dt.timedelta(hours=1)
            site = sites.setdefault(
                record["aqsid"],
                {
                    "earliest": end,
                    "stated": record["stated"],
                    "status": record["status"],
                    "first": record["index"],
                    "site": record["site"],
                },
            )
            if (site["stated"], site["status"]) != (record["stated"], record["status"]):
                raise AirnowRefused(
                    "site-disagrees",
                    f"record {record['index']} states another position or status for a site "
                    "an earlier record states",
                )
            site["earliest"] = min(site["earliest"], end)
        entities = {}
        for aqsid, site in sites.items():
            arguments: dict[str, Any] = {
                "source": stamp_base.model_copy(
                    update={"observed_at": site["earliest"], "transformations": [T_HOUR]}
                ),
                "system": SYSTEM,
                "station_id": aqsid,
                "site_class": "air_quality_site",
                "valid_from": site["earliest"],
                "station_table": self._site_table,
                "status": site["status"],
            }
            if site["stated"] is not None:
                arguments["stated_position"] = site["stated"]
                arguments["stated_position_basis"] = (
                    "the HourlyAQObs line's Latitude and Longitude, decimal degrees"
                )
            entity = site_entity(**arguments)
            entities[aqsid] = entity.model_copy(
                update={
                    "attributes": {
                        **entity.attributes,
                        "valid_from_basis": "the end of the earliest hour a line states for the site",
                    },
                    # The site's own fields as the first line naming it states them; every
                    # line's own are in its Event's residual.
                    "residual": Residual(
                        namespace=FORMAT_NAME,
                        data={"first_record": site["first"], "site": site["site"]},
                    ),
                }
            )
        events = []
        for record in records:
            start = record["start"]
            end = start + _dt.timedelta(hours=1)
            entity = entities[record["aqsid"]]
            position = entity.position
            transformations = [T_HOUR]
            if record["two_digit"]:
                transformations.append(T_TWO_DIGIT_YEAR)
            if any(r.measurement is not None for r in record["readings"]):
                transformations.append(T_NUMBER)
            contract = PointObservation(
                contract="point-observation/1",
                product_class="observation",
                time=TimeInputs(source_time_system=TIME_SYSTEM),
                locator=TableLocator(
                    kind="table",
                    row=record["index"],
                    header_lines=0 if form == HOURLY_DATA else 1,
                    frame_sha256=self._frame_sha256,
                ),
                quality_flags_basis=QUALITY_FLAGS_BASIS,
                station_id=record["aqsid"],
                station_namespace="EPA AQS site identifier (AQSID)",
                readings=record["readings"],
            )
            events.append(
                observation_event(
                    source=stamp_base.model_copy(
                        update={
                            "observed_at": start,
                            "record_index": record["index"],
                            "transformations": transformations,
                        }
                    ),
                    source_ids=[SourceId(system=SYSTEM, external_id=record["external"])],
                    observation=contract,
                    observed_at=end,
                    received_at=self.now(),
                    validity=TemporalValidity(effective=Period(start=start, end=end)),
                    related_entities=[entity.entity_id],
                    geometry=(
                        None
                        if position is None
                        else Point(coordinates=[position.lon, position.lat])
                    ),
                    residual=Residual(namespace=FORMAT_NAME, data=record["residual"]),
                )
            )
        return [*events, *entities.values()]
