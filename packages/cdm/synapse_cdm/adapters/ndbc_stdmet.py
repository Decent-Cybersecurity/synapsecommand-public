"""`ndbc_stdmet`, #26 in the ordinal table: one NDBC standard meteorological file -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One NDBC standard meteorological ("stdmet") text file as NDBC serves it: a realtime file
(`data/realtime2/<station>.txt`, the last 45 days), a current-year monthly file or a yearly
historical file once its gzip is unwrapped (`synapse-decode --container gzip`). It is
whitespace-aligned columns under one or two `#` lines — the column names, then their units — and
it is NOT CSV: `csv.reader` on a space delimiter reads a 19-column row as 41 fields
(gap-report-reconciliation R-05), so a row is `str.split()` and nothing else. `to_cdm` takes the
file's octets or its parsed twin (`<name>.parsed.json`: `header`, `units`, `rows`, every token as
written).

The format is read from the NDBC Web Data Guide (Version 2.0, June 2023) and NDBC's measurement
descriptions, both by reference; the quality-control handbook T80-10 (December 2023) is why no
flag is read. The two PDFs are pinned by SHA-256 in `fixtures/ndbc_stdmet/spec/ndbc_stdmet_pin.json`
and not carried.

THE HEADER DECIDES, NEVER THE POSITION
--------------------------------------
The column set changes with the file's year and kind (research-station-text F01): 19 columns
with `PTDY` in a realtime file, 18 in a historical one, 17 or 16 in older years, a two-digit
`YY`, no minute column, `BAR` where later files say `PRES`, and no units line before 2007. Every
value is therefore read by the NAME its column has in the header line, and a header naming a
column this module does not know is refused rather than guessed at. The year is the width its
column's name says: four digits under `#YY` and `YYYY`, two under `YY`. The `YY` layout is recorded
in one 1998 file only, so `98` is the one two-digit year read (as 1998); any other is refused, never
given a century. The realtime file prints the pressure tendency `PTDY` with its sign (`+0.3`, and a
signed zero), so a leading `+` is read there and refused in every other column.

WHAT IS MISSING, AND HOW THAT IS KNOWN
--------------------------------------
Two conventions mark a missing value, and which one a file uses is a fact about the file
(research-station-text F02, the measurement descriptions): a realtime file writes `MM`; a
historical file writes a run of 9s whose WIDTH depends on the column. A file whose header holds
`PTDY` is a realtime file (the descriptions: "PTDY is not in Historical files"); one without it is
historical. In a realtime file `MM` is an `Absence` with its mechanism named and a run of 9s is a
value. In a historical file a run of 9s is an `Absence` only at the width documented for its
column — WVHT, DPD, APD and TIDE `99.00`, MWD `999`, VIS `99.0`, WTMP `999.0`, the widths F02
observed — and a run of 9s at any other width, or in a column with no documented width, is
REFUSED: read as a number it would turn a missing value into a reading, and read as missing it
would turn a real 999.0 hPa into nothing. `MM` in a historical file is refused too. Nothing is
`0`, and nothing is guessed.

WHAT ONE FILE BECOMES
---------------------
One `ENVIRONMENTAL_OBSERVATION` Event per data row, in file order (realtime files are
newest-first, historical files oldest-first; `record_index` is the 0-based data row and is not a
time order), each carrying the `point-observation/1` contract with every data column of its row as
one reading; then the station's `Entity` (SENSOR, `site_entity`), last. A stdmet file states
neither its station nor where the station is (research-station-text F03): the station identifier
is the caller's `station_id` argument and the position comes only from the caller's
`StationTable`, else it is `None`. The row's instant is UTC (the descriptions: "Times are in
UTC"), and it is `observed_at` and both ends of `validity.effective`: the averaging windows the
descriptions give (WSPD over eight minutes, PTDY over three hours) are facts about a column, not a
sensing interval this module states. NDBC publishes no per-value quality flag in these files
(T80-10: hard-flagged values are withheld, soft flags are not printed), so the contract states that
absence with its basis.
"""

from __future__ import annotations

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
    Period,
    Residual,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.observation_contracts import (
    Absence,
    Datum,
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

#: `source.system` on every object and the system of every identifier: the buoy network.
SYSTEM = "NDBC"
FORMAT_NAME = "NDBC standard meteorological data (stdmet)"
FORMAT_VERSION = "NDBC Web Data Guide, Version 2.0 (June 2023)"
GUIDE = "the NDBC Web Data Guide (Version 2.0, June 2023)"
DESCRIPTIONS = "NDBC's measurement descriptions (faq/measdes.shtml)"

#: DECISIONS U-07: station text, one file of at most 8 MiB.
MAX_INPUT_BYTES = 8 * 1024 * 1024
#: The twin nests three containers; the harness loader's bound, as `readsb_trace` declares it.
MAX_DEPTH = 64

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_ndbc_stdmet_adapter.py::"

#: The year column's three spellings (research-station-text F01): `#YY` (realtime and recent
#: historical files, four-digit values), `YY` (the 1998 file, two-digit values), `YYYY` (the 2004
#: file, four digits).
YEAR_LABELS = ("#YY", "YY", "YYYY")

#: The two-digit years read under `YY`, and the year each names. F01 records the `YY` layout in
#: one file only, of 1998; the 2004 file already writes `YYYY`, and no file of the years between
#: or before is recorded. So `98` is the one two-digit year read, and any other is refused rather
#: than given a century.
TWO_DIGIT_YEARS = {"98": 1998}
#: The time columns after the year, and the optional minute column.
TIME_LABELS = ("MM", "DD", "hh")
MINUTE_LABEL = "mm"

#: Every data column a stdmet header may name (research-station-text F01's realtime, historical
#: and older headers). Two pairs name one quantity in two generations of the file.
COLUMNS = (
    "WDIR",
    "WD",
    "WSPD",
    "GST",
    "WVHT",
    "DPD",
    "APD",
    "MWD",
    "PRES",
    "BAR",
    "ATMP",
    "WTMP",
    "DEWP",
    "VIS",
    "PTDY",
    "TIDE",
)
SYNONYMS = (("WDIR", "WD"), ("PRES", "BAR"))

#: The column whose presence marks a realtime file (the descriptions: "PTDY is not in
#: Historical files").
REALTIME_MARKER = "PTDY"

#: The realtime files' marker for a missing value.
REALTIME_SENTINEL = "MM"

#: The historical files' missing-value runs of 9s, at the widths research-station-text F02
#: observed. A column absent here has no documented width, and a run of 9s in it is refused.
NINE_RUNS = {
    "WVHT": "99.00",
    "DPD": "99.00",
    "APD": "99.00",
    "TIDE": "99.00",
    "MWD": "999",
    "VIS": "99.0",
    "WTMP": "999.0",
}

#: The columns whose values are printed with an explicit sign. The realtime file
#: gap-report-reconciliation R-05 saved prints the pressure tendency as `+0.3`, `-0.5` and a
#: signed zero (`+0.0`, `-0.0`); every other column of it is unsigned or minus-signed, so a `+`
#: anywhere else is not a number this module reads.
SIGNED_COLUMNS = ("PTDY",)

#: A run of 9s: two or more 9s, then nothing or a decimal point and zeros.
_NINE_RUN = re.compile(r"9{2,}(\.0+)?")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_SIGNED_NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")
_TWO = re.compile(r"[0-9]{2}")
_FOUR = re.compile(r"[0-9]{4}")
_STATION = re.compile(r"[0-9A-Z]{5}")
_TOKEN = re.compile(r"\S+")

TIME_SYSTEM = TimeSystem(
    name="UTC",
    stated_by="source",
    basis=f"{DESCRIPTIONS}: 'Times are in UTC'; the year, MM, DD, hh and mm columns",
)

QUALITY_FLAGS_BASIS = (
    "NDBC prints no per-value quality flag in its text files: hard-flagged values are withheld "
    "from public release, soft flags are not printed, and the flags reach only the NOAA archive "
    "(NDBC T80-10, December 2023; research-station-text F12). A missing value is the absence its "
    "sentinel names."
)

MM_MECHANISM = (
    f"a realtime file (its header holds {REALTIME_MARKER}) writes a missing value as MM "
    f"({DESCRIPTIONS}; research-station-text F02)"
)
NO_UNITS_MECHANISM = (
    "the file has no units line (NDBC files before 2007, research-station-text F01 and F16), so "
    "the value's unit is not stated and the number stays in the Event's residual"
)
TIDE_DATUM = Datum(
    name="MLLW", namespace=f"{DESCRIPTIONS}: TIDE is in feet relative to mean lower low water"
)

T_INSTANT = (
    "the year, MM, DD, hh and mm columns are read as one UTC instant "
    f"({DESCRIPTIONS}: times are UTC)"
)
T_TWO_DIGIT_YEAR = (
    "the two-digit year 98 under a YY header is read as 1998: the YY layout is recorded only in a "
    "1998 file, and the 2004 file writes YYYY (research-station-text F01); no other two-digit "
    "year is read"
)
T_ON_THE_HOUR = "the header has no mm column, so the instant is read on the hour (minute 0)"
T_NUMBER = "each value's decimal text is read as a binary floating-point number"
T_SENTINEL = "a missing-value marker is an Absence carrying the marker as written"

FIXTURE_STATION = "EX001"
FIXTURE_STATIONS = StationTable(
    name="ndbc-stdmet-fixture-stations",
    basis="synthetic station positions written for the packaged fixtures on 2026-10-15 "
    "(fixtures/ndbc_stdmet/README.md); no real station is named",
    rows=[{"station_id": FIXTURE_STATION, "lat": 57.25, "lon": 21.5}],
)


def checked_station_id(value: object) -> str:
    """`value` if it is a station identifier as NDBC writes one, else the constructor's refusal;
    `synapse-decode` calls it before the file is read."""
    if type(value) is not str or _STATION.fullmatch(value) is None:
        raise ValueError("station_id is five upper-case letters or digits, as NDBC writes one")
    return value


class NdbcStdmetRefused(ValueError):
    """A file this module will not translate. `code` names the rule; the text names the line,
    row or column, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> NdbcStdmetRefused:
    refusal = NdbcStdmetRefused(code, "")
    refusal.args = (message,)
    return refusal


# -- octets to the twin --------------------------------------------------------------------------


def parse_file(octets: bytes) -> dict:
    """The file's lines as its twin: `header` and `units` (or `None`) as tokens, and `rows`.

    The first line is the header; the second is the units line exactly when it begins with `#`
    (a file before 2007 has none). Every later line is a data row, split on whitespace.
    """
    lines, _ = text_lines(octets, NdbcStdmetRefused)
    header = lines[0].split()
    units = None
    data = lines[1:]
    if data and data[0].startswith("#"):
        units, data = data[0].split(), data[1:]
    rows = []
    for number, line in enumerate(data, start=len(lines) - len(data) + 1):
        if line.lstrip().startswith("#"):
            raise NdbcStdmetRefused(
                "comment-among-rows", f"line {number} is a # line after the data began"
            )
        rows.append(line.split())
    return {"header": header, "units": units, "rows": rows}


def _check_twin(document: dict) -> dict:
    """A twin is exactly `{header, units, rows}`, each token a whole non-blank text."""
    if set(document) != {"header", "units", "rows"}:
        raise NdbcStdmetRefused(
            "not-a-twin", "a twin holds exactly the keys header, units and rows"
        )

    def tokens(value: Any, where: str) -> list[str]:
        if not isinstance(value, list) or not value:
            raise NdbcStdmetRefused("not-a-twin", f"{where} is not a non-empty list of tokens")
        for index, token in enumerate(value):
            if not twin_text(token) or _TOKEN.fullmatch(token) is None:
                raise NdbcStdmetRefused(
                    "not-a-twin", f"{where}[{index}] is not one whitespace-free token"
                )
        return value

    tokens(document["header"], "header")
    if document["units"] is not None:
        tokens(document["units"], "units")
    rows = document["rows"]
    if not isinstance(rows, list):
        raise NdbcStdmetRefused("not-a-twin", "rows is not a list")
    for index, row in enumerate(rows):
        tokens(row, f"rows[{index}]")
    return document


# -- the header ----------------------------------------------------------------------------------


def _read_header(header: list[str], units: list[str] | None) -> tuple[list[str], bool]:
    """The data columns, and whether the header has a minute column."""
    if header[0] not in YEAR_LABELS:
        raise NdbcStdmetRefused(
            "unknown-header", "the header's first column is not #YY, YY or YYYY"
        )
    if header[1:4] != list(TIME_LABELS):
        raise NdbcStdmetRefused(
            "unknown-header", "the header's second to fourth columns are not MM, DD and hh"
        )
    minute = len(header) > 4 and header[4] == MINUTE_LABEL
    data = header[5:] if minute else header[4:]
    if not data:
        raise NdbcStdmetRefused("unknown-header", "the header names no data column")
    for position, name in enumerate(data, start=len(header) - len(data) + 1):
        if name not in COLUMNS:
            raise NdbcStdmetRefused(
                "unknown-column",
                f"header column {position} is not a stdmet column this module reads",
            )
    if len(set(data)) != len(data):
        raise NdbcStdmetRefused("repeated-column", "the header names one column twice")
    for one, other in SYNONYMS:
        if one in data and other in data:
            raise NdbcStdmetRefused(
                "repeated-column", f"the header names both {one} and {other}, one quantity"
            )
    if units is not None:
        if len(units) != len(header):
            raise NdbcStdmetRefused(
                "width-mismatch", "the units line states another number of columns than the header"
            )
        if not units[0].startswith("#"):
            raise NdbcStdmetRefused("not-a-twin", "a units line begins with #")
    return data, minute


def _instant(row: list[str], label: str, minute: bool, number: int) -> tuple[_dt.datetime, bool]:
    """The row's UTC instant, and whether its year was two digits.

    The year is the width its header column names: four digits under `#YY` and `YYYY`, two under
    `YY` (research-station-text F01), and a two-digit year only where `TWO_DIGIT_YEARS` reads it.
    """
    year_text = row[0]
    two_digit = label == "YY"
    if (_TWO if two_digit else _FOUR).fullmatch(year_text) is None:
        raise NdbcStdmetRefused(
            "bad-time",
            f"row {number}: the year is not the width its header names (four digits under #YY "
            "and YYYY, two under YY)",
        )
    if two_digit:
        if year_text not in TWO_DIGIT_YEARS:
            raise NdbcStdmetRefused(
                "undocumented-year",
                f"row {number}: a two-digit year other than 98: the YY layout is recorded only "
                "in a 1998 file (research-station-text F01), so no other two-digit year is read",
            )
        year = TWO_DIGIT_YEARS[year_text]
    else:
        year = int(year_text)
    parts = row[1:5] if minute else row[1:4]
    if any(_TWO.fullmatch(p) is None for p in parts):
        raise NdbcStdmetRefused(
            "bad-time", f"row {number}: a month, day, hour or minute is not two digits"
        )
    month, day, hour = (int(p) for p in parts[:3])
    minutes = int(parts[3]) if minute else 0
    try:
        stamp = _dt.datetime(year, month, day, hour, minutes, tzinfo=_dt.timezone.utc)
    except ValueError:
        raise NdbcStdmetRefused(
            "bad-time", f"row {number}: the date and time name no instant"
        ) from None
    return stamp, two_digit


# -- the declaration -----------------------------------------------------------------------------


class NdbcStdmetAdapter(Adapter):
    """One NDBC stdmet file in; one Event per data row and the station's Entity out."""

    name = "ndbc_stdmet"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: `PUBLIC_GOVERNMENT`: NDBC is a National Weather Service centre, and the NWS states its
    #: information public domain unless noted otherwise (research-station-text F11).
    metadata = AdapterMetadata(
        id="ndbc_stdmet",
        name="NDBC standard meteorological (stdmet) text translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter ndbc_stdmet` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every row a structured residual on its own Event) with no LOST leaf on any parsed "
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
                "NDBC standard meteorological text (Web Data Guide Version 2.0): one realtime, "
                "monthly or yearly historical stdmet file per call, as its octets or its parsed "
                "twin; one ENVIRONMENTAL_OBSERVATION Event per data row carrying "
                "point-observation/1, and the station's Entity",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "not a bound of its own: one Event per data row and one "
                    "Entity, and a data row is at least seven octets (five two-digit time "
                    "columns, one value, the line end), so max_input_bytes bounds the count",
                    "max_decompressed_bytes": "this adapter inflates nothing: a yearly "
                    "historical file arrives as .txt.gz, and synapse-decode --container gzip "
                    "unwraps it under the host's own bounds before the adapter is handed the "
                    "text",
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, and every pass over the file is one walk of its lines and tokens; "
                    "the conformance suite's parser worker kills a decode that overruns its "
                    "deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "No NDBC document states a maximum size for a stdmet file. "
                            "DECISIONS U-07 rules one station-text file at most 8 MiB "
                            "(8 388 608 octets, `MAX_INPUT_BYTES`, "
                            "`adapters/ndbc_stdmet.py`); the design record's largest unit is a "
                            "realtime file of the last 45 days at ten-minute rows "
                            "(research-station-text F18), and a yearly historical file is one "
                            "year of them. The CO-OPS request range limits the same ruling "
                            "rests on (6-minute data one month a request, hourly one year, "
                            "research-station-text F05) are the station-text class's other "
                            "stated unit. " + _CAP
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
                            "(the twin, `rows`, a row). 64 (`MAX_DEPTH`, "
                            "`adapters/ndbc_stdmet.py`) is the harness loader's own bound and "
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
                "the header is read against a closed vocabulary of stdmet columns, and a column "
                "this module does not know is refused `unknown-column` rather than carried; "
                "the twin is exactly header, units and rows, so an injected key is refused "
                "`not-a-twin`"
            ),
        ),
        limitations=[
            Limitation(
                id="one-file-per-call",
                summary="exactly one stdmet file per call (a realtime, monthly or yearly "
                "historical file), as its octets or its parsed twin; a yearly .txt.gz is "
                "unwrapped by synapse-decode --container gzip. Other NDBC data types (.spec, "
                ".cwind, .ocean and the rest) are not this adapter's and their headers are "
                "refused",
            ),
            Limitation(
                id="station-from-the-caller",
                summary="a stdmet file states neither its station nor the station's position "
                "(research-station-text F03): the station identifier is the caller's station_id "
                "argument, and the position comes only from a caller's StationTable, else the "
                "Entity's position is null. Nothing is joined from activestations.xml or another "
                "file",
            ),
            Limitation(
                id="sentinel-conventions",
                summary="MM is read as missing only in a realtime file (a header with PTDY), and "
                "a run of 9s only in a historical file at the width research-station-text F02 "
                "observed for its column (WVHT, DPD, APD and TIDE 99.00, MWD 999, VIS 99.0, WTMP "
                "999.0). Any other run of 9s in a historical file is refused "
                "undocumented-sentinel, and so is a real reading of that shape in a column whose "
                "sentinel width is not documented (a 999.0 hPa pressure, a 99 degree wind "
                "direction): the widths for WDIR, WSPD, GST, PRES, ATMP and DEWP are not "
                "established, so this module refuses rather than guesses. MM in a historical "
                "file is refused",
            ),
            Limitation(
                id="two-digit-years",
                summary="the year is the width its header column names (four digits under #YY "
                "and YYYY, two under YY), and a two-digit year is read only as 98, 1998: the YY "
                "layout is recorded in a 1998 file only (research-station-text F01), so any other "
                "two-digit year is refused undocumented-year rather than given a century",
            ),
            Limitation(
                id="no-units-line",
                summary="a file with no units line (before 2007) states no unit, so each value "
                "is an Absence of cause unit_unknown and the number stays in the Event's "
                "residual row; nothing assumes the unit a later file states",
            ),
            Limitation(
                id="instant-not-window",
                summary="each row is one instant, observed_at and both ends of "
                "validity.effective; the averaging windows the measurement descriptions give for "
                "a column (WSPD over eight minutes, PTDY over three hours) are not stated as "
                "intervals",
            ),
            Limitation(
                id="no-quality-flags",
                summary="NDBC's text files print no per-value quality flag (NDBC T80-10, "
                "December 2023), so every contract states quality_flags_basis instead of flags",
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

    #: The ledger. Each Event's residual holds the header, the units line and ITS row as written,
    #: so row i of the twin is bound to object i (the Events come first, in row order, and the
    #: station's Entity last); the header and the units are found at their own paths.
    MAPPINGS = {
        "rows[*]": Mapping(to="#[*]:residual.data.row", kind="residual"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        station_id: str,
        station_table: StationTable | None = None,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
    ) -> None:
        """`station_id` is the station the file was recorded at, which the file does not state;
        `station_table` supplies positions the file does not state either. `source_hash` is the
        SHA-256 of the file as the host read it and `frame_sha256` that of the text it handed
        over when that is not the file (a gzip was unwrapped). All are values the caller computed
        or knows, and all are constructor arguments, so all are in the determinism tuple."""
        super().__init__(clock, synthetic=synthetic)
        checked_station_id(station_id)
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
        self._station_id = station_id
        self._station_table = station_table
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The packaged fixtures' context: station `EX001` and its synthetic position. It is the
        context of those fixtures only (`Adapter.fixture_instance`)."""
        return cls(
            clock=clock,
            synthetic=synthetic,
            station_id=FIXTURE_STATION,
            station_table=FIXTURE_STATIONS,
        )

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One file -> [one Event per data row, in file order, then the station's Entity]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            twin = parse_file(bytes(raw))
            header_lines = 1 if twin["units"] is None else 2
        elif isinstance(raw, dict):
            twin = _check_twin(raw)
            header_lines = 1 if twin["units"] is None else 2
        else:
            raise NdbcStdmetRefused(
                "unsupported-input",
                "a stdmet file is handed over as its octets or as its twin in a dict; text and "
                "other types are not taken",
            )
        return self._translate(twin, header_lines)

    # -- translation -----------------------------------------------------------------------------

    def _translate(self, twin: dict, header_lines: int) -> list[CDMBase]:
        header, units, rows = twin["header"], twin["units"], twin["rows"]
        columns, minute = _read_header(header, units)
        if not rows:
            raise NdbcStdmetRefused("no-data-row", "the file holds no data row")
        realtime = REALTIME_MARKER in columns
        first = len(header) - len(columns)
        read = []
        seen: dict[_dt.datetime, int] = {}
        for index, row in enumerate(rows):
            if len(row) != len(header):
                raise NdbcStdmetRefused(
                    "width-mismatch", f"row {index} has another number of columns than the header"
                )
            stamp, two_digit = _instant(row, header[0], minute, index)
            if stamp in seen:
                raise NdbcStdmetRefused(
                    "repeated-instant", f"row {index} states the instant of row {seen[stamp]}"
                )
            seen[stamp] = index
            readings, absent = [], False
            for offset, column in enumerate(columns):
                position = first + offset
                reading = self._reading(
                    column,
                    row[position],
                    None if units is None else units[position],
                    realtime,
                    f"row {index}, column {column}",
                )
                absent = absent or (
                    reading.absence is not None and reading.absence.cause == "sentinel"
                )
                readings.append(reading)
            read.append((index, row, stamp, two_digit, readings, absent))
        stamp_base = self.source_ref().model_copy(update={"source_hash": self._source_hash})
        earliest = min(stamp for _, _, stamp, _, _, _ in read)
        entity = site_entity(
            source=stamp_base.model_copy(
                update={"observed_at": earliest, "transformations": [T_INSTANT]}
            ),
            system=SYSTEM,
            station_id=self._station_id,
            site_class="buoy",
            valid_from=earliest,
            station_table=self._station_table,
        )
        entity = entity.model_copy(
            update={
                "attributes": {
                    **entity.attributes,
                    "station_id_basis": (
                        "the caller's station_id argument: a stdmet file does not state the "
                        "station it was recorded at (research-station-text F03)"
                    ),
                    "valid_from_basis": "the earliest instant a row of the file states",
                },
                # What the file states about itself rather than a row: its header and its units
                # line. Each row, with them, is its own Event's residual.
                "residual": Residual(
                    namespace=FORMAT_NAME, data={"header": list(header), "units": units}
                ),
            }
        )
        position = entity.position
        geometry = None if position is None else Point(coordinates=[position.lon, position.lat])
        events = []
        for index, row, stamp, two_digit, readings, absent in read:
            transformations = [T_INSTANT]
            if two_digit:
                transformations.append(T_TWO_DIGIT_YEAR)
            if not minute:
                transformations.append(T_ON_THE_HOUR)
            if any(r.measurement is not None for r in readings):
                transformations.append(T_NUMBER)
            if absent:
                transformations.append(T_SENTINEL)
            contract = PointObservation(
                contract="point-observation/1",
                product_class="observation",
                time=TimeInputs(source_time_system=TIME_SYSTEM),
                locator=TableLocator(
                    kind="table",
                    row=index,
                    header_lines=header_lines,
                    frame_sha256=self._frame_sha256,
                ),
                quality_flags_basis=QUALITY_FLAGS_BASIS,
                station_id=self._station_id,
                station_namespace="NDBC station identifier",
                readings=readings,
            )
            events.append(
                observation_event(
                    source=stamp_base.model_copy(
                        update={
                            "observed_at": stamp,
                            "record_index": index,
                            "transformations": transformations,
                        }
                    ),
                    source_ids=[
                        SourceId(
                            system=SYSTEM,
                            external_id=f"{self._station_id}/{times.render(stamp)}",
                        )
                    ],
                    observation=contract,
                    observed_at=stamp,
                    received_at=self.now(),
                    validity=TemporalValidity(effective=Period(start=stamp, end=stamp)),
                    related_entities=[entity.entity_id],
                    geometry=geometry,
                    residual=Residual(
                        namespace=FORMAT_NAME,
                        data={"header": list(header), "units": units, "row": list(row)},
                    ),
                )
            )
        return [*events, entity]

    def _reading(
        self, column: str, token: str, unit: str | None, realtime: bool, where: str
    ) -> Reading:
        named: dict[str, Any] = {"name": column, "namespace": "NDBC stdmet header line"}
        if column == "TIDE":
            named["datum"] = TIDE_DATUM
        if token == REALTIME_SENTINEL:
            if not realtime:
                raise NdbcStdmetRefused(
                    "mm-in-historical-file",
                    f"{where}: MM in a file whose header has no {REALTIME_MARKER}, "
                    "where a missing value is a run of 9s",
                )
            return Reading(
                **named, absence=Absence(cause="sentinel", mechanism=MM_MECHANISM, sentinel=token)
            )
        if not realtime and _NINE_RUN.fullmatch(token):
            if NINE_RUNS.get(column) != token:
                raise NdbcStdmetRefused(
                    "undocumented-sentinel",
                    f"{where}: a run of 9s at a width no document this module is "
                    "written from gives for the column",
                )
            return Reading(
                **named,
                absence=Absence(
                    cause="sentinel",
                    mechanism=(
                        f"a historical file writes a missing {column} as a run of 9s of this "
                        f"width ({DESCRIPTIONS}; the width research-station-text F02 observed)"
                    ),
                    sentinel=token,
                ),
            )
        grammar = _SIGNED_NUMBER if column in SIGNED_COLUMNS else _NUMBER
        if grammar.fullmatch(token) is None:
            raise NdbcStdmetRefused(
                "not-a-number",
                f"{where}: neither a number, MM nor a documented run of 9s",
            )
        # Checked before the unit: a number no double holds is refused whether or not the file
        # states its unit, so the same row never translates in one layout and fails in another.
        value = decimal_float(token)
        if value is None:
            raise NdbcStdmetRefused(
                "number-out-of-range",
                f"{where}: the number lies outside what a binary double holds",
            )
        if unit is None:
            return Reading(
                **named, absence=Absence(cause="unit_unknown", mechanism=NO_UNITS_MECHANISM)
            )
        return Reading(
            **named,
            measurement=Measurement(
                value=value, unit=unit, unit_namespace="NDBC stdmet units line"
            ),
        )
