"""The four observation payload contracts, and the helpers every observation adapter builds with.

WHAT AN OBSERVATION IS IN THE CDM
---------------------------------
No fifth kind. An observation is an `Event` of type `ENVIRONMENTAL_OBSERVATION` whose
`payload["observation"]` validates against one of four named contracts, on the c2sim pattern
(`adapters/c2sim.py`, `c2sim-order/1`): a pydantic model a consumer calls `model_validate` on, not
a model registered in `PAYLOAD_MODELS`, because a registration binds every producer of the event
type to one shape and four classes cannot share one.

    gridded-field/1        a field on a grid: a GRIB2 message, a gridded product's variable
    point-observation/1    readings at one station: a buoy row, a tide-gauge sample, a monitor hour
    radar-sweep/1          one elevation of one radar volume, its moments by reference
    imagery-product/1      a product, band or granule file: a satellite band, a raster tile

The station, buoy or radar is an `Entity` (`site_entity`) that the Event names in
`related_entities`. The contract carries what the canonical objects cannot, and nothing they can.

THE RULES THE MODELS HOLD, EACH BECAUSE THE ALTERNATIVE IS A SILENT ERROR
-----------------------------------------------------------------------
- A measured value carries its unit verbatim and the table the unit was read from
  (`Measurement`). There is no unit enum: the first unit nobody foresaw would be a MAJOR removal
  problem, and the namespace keeps the string meaningful without a CDM table. A value whose unit
  cannot be read is NOT stated — the `VerticalUnit` rule — and a sentinel (`MM`, `-3`) is an
  `Absence` with its mechanism named, never a number that happens to be large or negative.
- The grid is the SOURCE's structure, opaque and verbatim, and it has no `crs` key at any depth:
  `geo.py`'s rule is that an adapter converts to WGS84 or refuses, so the canonical geometry is
  the WGS84 footprint on `Event.geometry` and the grid block is what a consumer needs to open the
  array, never a second coordinate system to reason in.
- A level and a datum are carried as the source states them. `Position.alt_m` is HAE metres only,
  and a 500 hPa surface or a NAVD88 height is neither.
- Quality flags are typed and verbatim (`QualityFlag`), interpreted by nobody; where the format
  publishes none, the contract says so with a basis instead of carrying an empty list that reads
  like "nothing was wrong".
- The values are by REFERENCE by default (a locator, the shape and packing needed to open them and
  a summary), or inline up to `MAX_INLINE_VALUES`. A golden that inlines a full model field is a
  document nobody can read.
- Processing clocks — a production time, a run letter, a creation stamp — live in
  `product_version` and in no key ending `_at`, `_from` or `_to`, so nothing can mistake one for a
  time semantic. `observed_at` is the END of the sensing interval for an observation and the
  REFERENCE time for a model product (`observation_event` checks both), never a future valid
  instant; every interval is `Event.validity.effective`.
- The time system a stamp was read in is stated (`TimeSystem`): by the source, or by the caller
  when the source leaves it to a request parameter, because a naive stamp parsed as UTC is a
  five-hour error that raises nothing.

Every block is closed (`extra="forbid"`) and frozen. A key the contract does not name is a
mistake, not data: the source's own leftovers go to the Event's `residual`, under its namespace.

PUBLICATION
-----------
`python -m synapse_cdm.observation_contracts --out schemas/observation` writes one JSON Schema per
contract, generated from these models and never hand-written; `--check` fails when the files are
stale, as `python -m synapse_cdm.schemas --check` does for the CDM's own. They are a non-union
artefact for consumers that do not run Python, not a `oneOf` branch of the CDM.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import math
import pathlib
import re
import sys
import types
import typing
import uuid
from typing import Annotated, Any, Iterable, Literal, Mapping, Sequence, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from synapse_cdm import canonical, ids, lossless, times
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
    VerticalReference,
    VerticalUnit,
)
from synapse_cdm.geo import Geometry, VerticalPosition
from synapse_cdm.manifest import Limitation, LimitBasis, LimitKind
from synapse_cdm.models import (
    Entity,
    Event,
    OperationalStatus,
    Position,
    Quality,
    Residual,
    SourceId,
    SourceRef,
    TemporalValidity,
    Timestamp,
)

#: The four contract names, in the order the documentation lists them.
CONTRACTS = ("gridded-field/1", "point-observation/1", "radar-sweep/1", "imagery-product/1")

#: Where an `ENVIRONMENTAL_OBSERVATION` Event carries its contract.
PAYLOAD_KEY = "observation"

#: The register's six classes of product, verbatim in meaning. A class is a fact about the
#: product, not a judgement about its quality: an analysis is not a worse observation.
ProductClass = Literal[
    "observation", "forecast", "analysis", "reanalysis", "modelled_estimate", "reference"
]

#: The classes whose `observed_at` is the reference time of the model run.
MODEL_PRODUCT_CLASSES = ("forecast", "analysis", "reanalysis", "modelled_estimate")

#: How many values a contract may carry inline. Values past it go by reference.
MAX_INLINE_VALUES = 4096

#: Why that number. A bound with no recorded basis is a claim nobody has to justify.
MAX_INLINE_VALUES_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "A cap chosen on 2026-10-15 so that a golden which carries values stays a document a "
        "reader can review: 4096 values is a 64 x 64 window. The design record's figures put "
        "every whole product far above it — an HRRR field is 1799 x 1059 cells and the smallest "
        "honest COG unit a 512 x 512 tile (design-judge DJ-10, research-raster F9) — so a whole "
        "field always goes by reference and inline values are a bounded window or a station's "
        "handful."
    ),
    enforced_at=(
        "observation_contracts.ValuesInline: `values` has max_length MAX_INLINE_VALUES and the "
        "product of `shape` must equal its length, before any contract holding it exists"
    ),
    test="tests/test_cdm_observation_contracts.py::test_inline_values_stop_at_the_cap",
)

#: The `EntityType` of each site class an observation adapter names. Every class is SENSOR until
#: the contract owner rules a class FACILITY; moving one is one row. A class not listed is refused
#: by `site_entity` rather than given a default, so a new site class is a decision somebody makes.
SITE_ENTITY_TYPES: Mapping[str, EntityType] = types.MappingProxyType(
    {
        "weather_station": EntityType.SENSOR,
        "buoy": EntityType.SENSOR,
        "tide_gauge": EntityType.SENSOR,
        "air_quality_site": EntityType.SENSOR,
        "radar_site": EntityType.SENSOR,
    }
)

_DIGEST = re.compile(r"[0-9a-f]{64}")

#: An instant a caller hands in: RFC 3339 with seconds, at most six fractional digits and an
#: explicit zone. A stamp without a zone is refused, because `times.parse` would read it as UTC.
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")

_BASIS_MAX = 1024


# -- field types ---------------------------------------------------------------------------------


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("the text is blank; a blank string states nothing")
    return value


#: Source text: a string, never a number coerced into one, and never blank.
Text = Annotated[str, Field(strict=True, min_length=1), AfterValidator(_not_blank)]
#: A finite number. An integer is accepted and a boolean is not.
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
#: A source value as the source wrote it: a flag's value, a fill value.
Verbatim = Union[StrictBool, StrictInt, Number, Text]


# -- what a JSON-reading adapter may trust in a parsed document ----------------------------------

#: The largest integer magnitude a double holds. `json` reads an integer of any length, and
#: `math.isfinite` or `float()` raises `OverflowError` on one past the double range instead of
#: answering, so an integer beyond this is not a number an observation adapter reads.
LARGEST_JSON_INTEGER = int(sys.float_info.max)


def json_number(value: object) -> bool:
    """Whether `value` is a number an adapter reads from a parsed JSON document: an int or a
    float, not a boolean, not NaN or an infinity, and not an integer no double holds.

    The integer test comes first and compares integers only (`readsb_trace`'s rule, lifted here
    on 2026-10-15 so every JSON-reading adapter shares it): `math.isfinite` on an integer past
    the double range raises `OverflowError` rather than answering. The caller refuses a value
    this rejects by the rule of the element that states it, so a refusal never depends on how
    large the number was.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int):
        return -LARGEST_JSON_INTEGER <= value <= LARGEST_JSON_INTEGER
    return math.isfinite(value)


def utf8_text(text: str) -> bool:
    """Whether `text` is Unicode a UTF-8 serialisation can carry.

    JSON's `\\ud800` escape decodes to a lone surrogate, which no UTF-8 text holds, so an object
    built from one validates and then cannot be written; an adapter refuses a string or a key
    for which this is False, naming its path and never the text (lifted from `readsb_trace` on
    2026-10-15).
    """
    if text.isascii():
        return True
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# -- what a text-reading adapter may trust in a file of lines ------------------------------------

#: A character no station-text line holds: the C0 controls but the line ends, DEL and the C1
#: controls. A tab is refused with them, because a whitespace-split reader would read one as a
#: column boundary that a fixed-column writer never wrote.
_CONTROL = re.compile(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def text_lines(octets: bytes, refused: Any) -> tuple[list[str], str]:
    """The lines of a station-text file and the line end it uses, `"LF"` or `"CRLF"`.

    Shared by the three station-text adapters (2026-10-15), so a file of lines is read one way:
    UTF-8 without a byte-order mark, no control character, no blank line, ONE line-end style for
    the whole file, and a line end after the last line. The last rule is what makes a file cut
    short refusable: without it a row cut inside a number would read as a shorter number. A cut
    at a line end leaves a whole shorter file, which is read as one.

    `refused(code, text)` builds the adapter's own refusal; the text names a line by its 1-based
    number and never quotes it.
    """
    if not octets:
        raise refused("empty-file", "the file holds no line")
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise refused("not-utf8", "the file is not UTF-8 text") from None
    if text.startswith("\ufeff"):
        raise refused("byte-order-mark", "the file opens with a byte-order mark")
    if not text.endswith("\n"):
        raise refused(
            "unterminated-line",
            "the last line has no line end: the file is cut short or is not whole lines",
        )
    lines = text[:-1].split("\n")
    crlf = lines[0].endswith("\r")
    for number, line in enumerate(lines, start=1):
        if line.endswith("\r") != crlf:
            raise refused("mixed-line-ends", f"line {number} ends otherwise than line 1")
        if crlf:
            line = line[:-1]
            lines[number - 1] = line
        if "\r" in line or _CONTROL.search(line) is not None:
            raise refused("control-character", f"line {number} holds a control character")
        if not line.strip():
            raise refused("blank-line", f"line {number} is blank")
    return lines, "CRLF" if crlf else "LF"


def twin_text(value: object) -> bool:
    """Whether a string handed over in a parsed twin is one a text file could have held: a
    `str`, Unicode a UTF-8 serialisation carries, and no character `text_lines` refuses."""
    return (
        type(value) is str
        and utf8_text(value)
        and "\n" not in value
        and "\r" not in value
        and "\ufeff" not in value
        and _CONTROL.search(value) is None
    )


#: The decimal digits of `LARGEST_JSON_INTEGER` (309). A text of more digits names no integer a
#: double holds, and it is refused before `int()` sees it: `int()` raises on a text past the
#: interpreter's digit limit (4300 by default, 640 at the least) instead of answering.
LARGEST_INTEGER_DIGITS = len(str(LARGEST_JSON_INTEGER))


def decimal_integer(text: str) -> int | None:
    """The integer a decimal text states, or `None` when no double holds it.

    The caller has already held `text` to its own grammar (ASCII digits after an optional sign).
    Shared by the station-text adapters (2026-10-15), so a flag or a count of any length is
    refused by the adapter's own typed rule, never by a `ValueError` from `int()`.
    """
    digits = text[1:] if text.startswith(("+", "-")) else text
    if len(digits) > LARGEST_INTEGER_DIGITS:
        return None
    value = int(text)
    return value if -LARGEST_JSON_INTEGER <= value <= LARGEST_JSON_INTEGER else None


def decimal_float(text: str) -> float | None:
    """The binary double a decimal text reads as, or `None` when it reads past the double range
    (to an infinity) or names a non-zero number that reads as zero.

    The caller has already held `text` to its own grammar. `float()` answers a decimal of 400
    digits with an infinity, which the contract refuses as a `ValidationError` rather than the
    adapter's own refusal; this helper lets the adapter refuse it first, by its own rule
    (2026-10-15, shared by the station-text adapters). An underflow is refused with it, because
    a stated non-zero value read as 0.0 is a value the file did not state.
    """
    value = float(text)
    if not math.isfinite(value):
        return None
    if value == 0.0 and re.search(r"[1-9]", re.split(r"[eE]", text)[0]) is not None:
        return None
    return value


class _Block(BaseModel):
    """Every block is closed and frozen: a key the contract does not name is a mistake."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _product(shape: Sequence[int]) -> int:
    return math.prod(shape)


# -- measurements, units, absences ---------------------------------------------------------------


class Measurement(_Block):
    """One value with the unit the source stated and the table it was read from."""

    value: Number
    unit: Text = Field(description="The source's own unit string, verbatim.")
    unit_namespace: Text = Field(
        description="Where the unit was read: a GRIB table, a CF attribute, a header line."
    )


class UnitRef(_Block):
    """The unit of an array of values, which a `Measurement` would repeat per value."""

    unit: Text
    unit_namespace: Text


class Absence(_Block):
    """A value the source does not state, and how that is known.

    `sentinel` — the source wrote a marker meaning "missing" (`MM`, `-3`); `sentinel` is the
    marker verbatim and `mechanism` names the table or rule that says what it means.
    `unit_unknown` — the source wrote a number whose unit cannot be read; the number is NOT
    carried here (a value with no unit is not a value), and the adapter parks it in its residual.
    """

    cause: Literal["sentinel", "unit_unknown"]
    mechanism: Text
    sentinel: Text | None = None

    @model_validator(mode="after")
    def _the_marker_belongs_to_a_sentinel(self) -> Absence:
        if self.cause == "sentinel" and self.sentinel is None:
            raise ValueError("a sentinel absence states the marker the source wrote")
        if self.cause == "unit_unknown" and self.sentinel is not None:
            raise ValueError(
                "a unit_unknown absence carries no marker: the unreadable value belongs in the "
                "residual, never beside a contract field that says it is not stated"
            )
        return self


class Quantity(_Block):
    """What is measured, named the source's way: a short name, a table code, or both."""

    name: Text | None = None
    code: Text | None = None
    namespace: Text

    @model_validator(mode="after")
    def _named_somehow(self) -> Quantity:
        if self.name is None and self.code is None:
            raise ValueError("a quantity states a name, a code or both")
        return self


class VerticalLevel(_Block):
    """A level as the source states it (a GRIB Table 4.5 surface, a sensor height)."""

    type: Text | None = None
    code: Text | None = None
    value: Number | None = None
    unit: Text | None = None
    namespace: Text

    @model_validator(mode="after")
    def _a_value_has_a_unit(self) -> VerticalLevel:
        if self.type is None and self.code is None:
            raise ValueError("a level states its type, its code or both")
        if self.value is not None and self.unit is None:
            raise ValueError("a level value without a unit is not stated: carry neither")
        if self.unit is not None and self.value is None:
            raise ValueError("a level unit without a value states nothing")
        return self


class Datum(_Block):
    """The vertical datum a height is referred to (NAVD88, MLLW), as the source names it."""

    name: Text
    namespace: Text


# -- the grid ------------------------------------------------------------------------------------


def _json_problems(value: Any, path: str) -> list[str]:
    """Every `crs` key and every non-finite number below `value`, by path."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() == "crs":
                found.append(f"{path}.{key}: a crs key")
            found += _json_problems(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += _json_problems(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        found.append(f"{path}: a non-finite number")
    return found


class Grid(_Block):
    """The source's grid definition, verbatim and opaque.

    `parameters` is the template's own content under the source's own names (GRIB section 3
    octets, CF grid-mapping attributes, GeoKeys, world-file terms). It is never promoted into a
    canonical field and it never holds a `crs` key: the canonical geometry is the WGS84
    footprint the adapter converts, on `Event.geometry`.
    """

    namespace: Text = Field(description="Whose grid vocabulary: a GRIB table, CF, GeoTIFF.")
    template: Text = Field(description="The template or projection identifier, verbatim.")
    shape: list[PositiveInt] = Field(min_length=1, description="Cells per axis, source order.")
    scanning_mode: Text | None = None
    cell_size: list[Measurement] | None = Field(
        default=None, description="One per axis of `shape`, in the same order, verbatim units."
    )
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_crs_and_one_size_per_axis(self) -> Grid:
        if self.cell_size is not None and len(self.cell_size) != len(self.shape):
            raise ValueError("cell_size states one size per axis of shape")
        problems = _json_problems(self.parameters, "parameters")
        if problems:
            raise ValueError(
                "the grid's parameters hold "
                + "; ".join(problems)
                + ". There is no crs field and there will not be one: the adapter converts to "
                "WGS84 for Event.geometry, and every number in a contract is finite"
            )
        return self


# -- quality -------------------------------------------------------------------------------------


class QualityFlag(_Block):
    """One quality flag, verbatim: its name, its value, the table it belongs to, what it covers.

    Nobody interprets it here — not into a confidence, not into a pass/fail. `applies_to` names
    the reading, moment, variable or `record` the flag describes; its value is never an instant.
    """

    name: Text
    value: Verbatim
    namespace: Text
    applies_to: Text


# -- where in the source -------------------------------------------------------------------------


class _Locator(_Block):
    """Where in the file the host read the object came from. Ordinals are 0-based unless named
    otherwise, like `SourceRef.record_index`."""

    frame_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = Field(
        default=None,
        description="SHA-256 of the frame handed to the adapter, when it is not the whole file "
        "`source.source_hash` digests. Computed by the host, never by the adapter.",
    )
    granule_id: Text | None = Field(
        default=None, description="The granule a band file belongs to, shared by its files."
    )


class GribLocator(_Locator):
    kind: Literal["grib"]
    message: NonNegativeInt = Field(description="The message's 0-based ordinal in the file.")
    field: NonNegativeInt = Field(description="The field's 0-based ordinal in the message.")
    byte_offset: NonNegativeInt = Field(description="The message's first octet in the file.")


class RadarLocator(_Locator):
    kind: Literal["radar"]
    ldm_record: NonNegativeInt
    message: NonNegativeInt
    elevation_number: PositiveInt = Field(
        description="The elevation NUMBER, 1-based as the volume numbers it; never the angle, "
        "which a rescan repeats."
    )
    azimuth_number: PositiveInt | None = None
    moment: Text | None = None


class TableLocator(_Locator):
    kind: Literal["table"]
    row: NonNegativeInt = Field(description="The 0-based data record, after the header lines.")
    header_lines: NonNegativeInt


class RasterWindow(_Block):
    column: NonNegativeInt
    row: NonNegativeInt
    width: PositiveInt
    height: PositiveInt


class RasterLocator(_Locator):
    kind: Literal["raster"]
    band_file: Text | None = None
    ifd: NonNegativeInt | None = None
    tile: NonNegativeInt | None = None
    window: RasterWindow | None = None

    @model_validator(mode="after")
    def _points_somewhere(self) -> RasterLocator:
        if all(v is None for v in (self.band_file, self.ifd, self.tile, self.window)):
            raise ValueError("a raster locator names a band file, an IFD, a tile or a window")
        return self


class ParquetLocator(_Locator):
    kind: Literal["parquet"]
    row_group: NonNegativeInt
    row: NonNegativeInt = Field(description="The 0-based row inside the row group.")


class ArrayLocator(_Locator):
    kind: Literal["netcdf", "hdf5"]
    group: Annotated[str, Field(strict=True, pattern=r"^/")] = Field(
        description="The group path from the root, `/` for the root itself."
    )
    variable: Text
    index: list[NonNegativeInt] = Field(
        default_factory=list, description="An element's index; empty = the whole variable."
    )


Locator = Annotated[
    Union[GribLocator, RadarLocator, TableLocator, RasterLocator, ParquetLocator, ArrayLocator],
    Field(discriminator="kind"),
]


# -- values --------------------------------------------------------------------------------------


class ArraySummary(_Block):
    """What a consumer may know about an array without opening it."""

    count: NonNegativeInt
    missing_count: NonNegativeInt
    min: Number | None = None
    max: Number | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ArraySummary:
        if self.missing_count > self.count:
            raise ValueError("missing_count exceeds count")
        if (self.min is None) != (self.max is None):
            raise ValueError("min and max are stated together or not at all")
        if self.min is not None and self.max is not None:
            if self.missing_count == self.count:
                raise ValueError("an array with no stated value has no min or max")
            if self.min > self.max:
                raise ValueError("min exceeds max")
        return self


class ValuesByReference(_Block):
    """The values stay in the source; this says where they are and how to open them."""

    mode: Literal["reference"]
    locator: Locator
    shape: list[PositiveInt] = Field(min_length=1)
    dtype: Text = Field(description="The stored type, verbatim.")
    encoding: Text = Field(description="The packing or compression, verbatim.")
    scale: Number | None = None
    offset: Number | None = None
    fill: Verbatim | None = None
    summary: ArraySummary | None = None

    @model_validator(mode="after")
    def _summary_counts_the_shape(self) -> ValuesByReference:
        if self.summary is not None and self.summary.count != _product(self.shape):
            raise ValueError("summary.count is not the number of cells shape describes")
        return self


class ValuesInline(_Block):
    """At most `MAX_INLINE_VALUES` values, in the source's order. `None` is a missing value, and
    a contract with one names the mechanism that made it missing."""

    mode: Literal["inline"]
    shape: list[PositiveInt] = Field(min_length=1)
    values: list[Number | None] = Field(max_length=MAX_INLINE_VALUES)
    missing_mechanism: Text | None = None

    @model_validator(mode="after")
    def _shape_and_missing(self) -> ValuesInline:
        if _product(self.shape) != len(self.values):
            raise ValueError("the number of values is not the number of cells shape describes")
        has_missing = any(v is None for v in self.values)
        if has_missing and self.missing_mechanism is None:
            raise ValueError("a missing value needs its missing_mechanism")
        if not has_missing and self.missing_mechanism is not None:
            raise ValueError("missing_mechanism is stated and no value is missing")
        return self


Values = Annotated[Union[ValuesByReference, ValuesInline], Field(discriminator="mode")]


# -- time and version ----------------------------------------------------------------------------


class CodedValue(_Block):
    """A code from a named table, verbatim; `meaning` only as the table's own words."""

    code: Text
    namespace: Text
    meaning: Text | None = None


class TimeSystem(_Block):
    """The time system the source's stamps were read in, and who said so."""

    name: Text = Field(description="Verbatim: UTC, GMT, gmt, GPS.")
    stated_by: Literal["source", "caller"]
    basis: Text = Field(description="Where it was read, or which declared argument said it.")


class TimeInputs(_Block):
    """The time facts a model product states beside `observed_at` and `Event.validity`."""

    source_time_system: TimeSystem
    reference_time: Timestamp | None = None
    reference_time_significance: CodedValue | None = Field(
        default=None, description="GRIB2 Table 1.2, verbatim, where the source states one."
    )
    forecast_offset: Measurement | None = None
    statistical_process: CodedValue | None = Field(
        default=None, description="GRIB2 Table 4.10, verbatim, where the source states one."
    )

    @field_validator("reference_time", mode="before")
    @classmethod
    def _reference_time_states_its_zone(cls, value: object) -> object:
        """An aware datetime, or the one wire form `times.render` writes; nothing else.

        The CDM's `Timestamp` reads a naive string as UTC on the Python path, which is the path
        `parse_observation` takes; for a contract that states its source time system that would
        be the silent offset `TimeSystem` exists to prevent. This runs before `Timestamp`'s own
        reading, on both paths, and never quotes the value.
        """
        if value is None:
            return value
        if isinstance(value, _dt.datetime) and value.tzinfo is not None:
            return value
        if type(value) is str and times.TIMESTAMP_RE.fullmatch(value) is not None:
            return value
        raise ValueError(
            "reference_time is an aware datetime or the wire form 2026-04-29T06:12:44.000Z; a "
            "stamp without a zone is refused, never read as UTC"
        )

    @model_validator(mode="after")
    def _significance_qualifies_a_reference(self) -> TimeInputs:
        if self.reference_time is None and (
            self.reference_time_significance is not None or self.forecast_offset is not None
        ):
            raise ValueError("a significance or a forecast offset qualifies a reference_time")
        return self


class ProductVersion(_Block):
    """Which run, which version, produced when and by whom — processing facts, never times."""

    run: Text | None = None
    version: Text | None = None
    production_time_verbatim: Text | None = None
    producer: Text | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> ProductVersion:
        if all(
            v is None
            for v in (self.run, self.version, self.production_time_verbatim, self.producer)
        ):
            raise ValueError("an empty product_version is the absence of one: omit it")
        return self


# -- the contracts -------------------------------------------------------------------------------


class _Contract(_Block):
    product_class: ProductClass
    product_version: ProductVersion | None = None
    time: TimeInputs
    locator: Locator
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    quality_flags_basis: Text | None = Field(
        default=None,
        description="Why there are no quality flags: the format publishes none, or none is set. "
        "Required exactly when quality_flags is empty.",
    )

    @model_validator(mode="after")
    def _flags_or_their_absence(self) -> _Contract:
        if not self.quality_flags and self.quality_flags_basis is None:
            raise ValueError(
                "no quality flag and no quality_flags_basis: an empty list reads as 'nothing "
                "was wrong', so the absence is stated with its reason"
            )
        if self.quality_flags and self.quality_flags_basis is not None:
            raise ValueError("quality_flags_basis states an absence and flags are present")
        return self


def _inline_needs_a_unit(values: Any, unit: UnitRef | None, where: str) -> None:
    if isinstance(values, ValuesInline) and unit is None:
        raise ValueError(
            f"{where} carries inline values and no unit: a value whose unit is not "
            "stated is not stated"
        )


class Reading(_Block):
    """One named quantity at a station: a measurement or an absence, never both."""

    name: Text
    namespace: Text
    measurement: Measurement | None = None
    absence: Absence | None = None
    level: VerticalLevel | None = None
    datum: Datum | None = None

    @model_validator(mode="after")
    def _one_of_the_two(self) -> Reading:
        if (self.measurement is None) == (self.absence is None):
            raise ValueError("a reading states a measurement or an absence, exactly one")
        return self


class GriddedField(_Contract):
    """`gridded-field/1`: one field on one grid."""

    contract: Literal["gridded-field/1"]
    quantity: Quantity
    unit: UnitRef | None = None
    level: VerticalLevel | None = None
    datum: Datum | None = None
    grid: Grid
    values: Values

    @model_validator(mode="after")
    def _unit(self) -> GriddedField:
        _inline_needs_a_unit(self.values, self.unit, "the field")
        return self


class PointObservation(_Contract):
    """`point-observation/1`: the readings one record states for one station."""

    contract: Literal["point-observation/1"]
    station_id: Text = Field(description="The station's identifier, verbatim.")
    station_namespace: Text
    readings: list[Reading] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_reading_twice(self) -> PointObservation:
        seen = set()
        for reading in self.readings:
            key = (reading.name, reading.namespace, reading.level)
            if key in seen:
                raise ValueError("a reading is stated twice for one name, namespace and level")
            seen.add(key)
        return self


class RadarMoment(_Block):
    """One moment of a sweep (reflectivity, velocity …), its gates and its values."""

    name: Text
    namespace: Text
    unit: UnitRef | None = None
    gate_count: PositiveInt
    first_gate_range: Measurement
    gate_interval: Measurement
    values: Values

    @model_validator(mode="after")
    def _unit(self) -> RadarMoment:
        _inline_needs_a_unit(self.values, self.unit, "the moment")
        return self


class RadarSweep(_Contract):
    """`radar-sweep/1`: one elevation of one volume, by elevation number."""

    contract: Literal["radar-sweep/1"]
    site_id: Text
    elevation_number: PositiveInt
    elevation_angle: Measurement | None = None
    radial_count: PositiveInt
    coverage_pattern: CodedValue | None = None
    moments: list[RadarMoment] = Field(min_length=1)

    @model_validator(mode="after")
    def _the_locator_is_this_sweep(self) -> RadarSweep:
        if not isinstance(self.locator, RadarLocator):
            raise ValueError("a radar sweep is located by a radar locator")
        if self.locator.elevation_number != self.elevation_number:
            raise ValueError("the locator names another elevation than the sweep's")
        names = [m.name for m in self.moments]
        if len(set(names)) != len(names):
            raise ValueError("a moment is stated twice")
        return self


class ImageryProduct(_Contract):
    """`imagery-product/1`: one product, band or granule file, by reference."""

    contract: Literal["imagery-product/1"]
    product: Quantity
    band: Quantity | None = None
    wavelength: Measurement | None = None
    unit: UnitRef | None = None
    grid: Grid | None = None
    values: Values | None = None

    @model_validator(mode="after")
    def _unit(self) -> ImageryProduct:
        _inline_needs_a_unit(self.values, self.unit, "the product")
        return self


#: Contract name -> model.
MODELS: Mapping[str, type[_Contract]] = types.MappingProxyType(
    {
        "gridded-field/1": GriddedField,
        "point-observation/1": PointObservation,
        "radar-sweep/1": RadarSweep,
        "imagery-product/1": ImageryProduct,
    }
)

ObservationContract = Annotated[
    Union[GriddedField, PointObservation, RadarSweep, ImageryProduct],
    Field(discriminator="contract"),
]

_CONTRACT_ADAPTER: TypeAdapter = TypeAdapter(ObservationContract)


def parse_observation(document: Any) -> _Contract:
    """The contract a payload's `observation` member holds, validated by its `contract` name."""
    return _CONTRACT_ADAPTER.validate_python(document)


def contract_of(event: Event) -> _Contract:
    """The contract an `ENVIRONMENTAL_OBSERVATION` Event carries. Another event type is refused:
    its payload is not an observation, whatever keys it holds."""
    if event.event_type is not EventType.ENVIRONMENTAL_OBSERVATION:
        raise ValueError("the event is not an ENVIRONMENTAL_OBSERVATION")
    if PAYLOAD_KEY not in event.payload:
        raise ValueError("the event's payload has no observation member")
    return parse_observation(event.payload[PAYLOAD_KEY])


# -- the injected time convention ----------------------------------------------------------------


def parse_instant(text: object) -> _dt.datetime:
    """A caller's RFC 3339 instant, which must carry its zone, as an aware UTC datetime."""
    if type(text) is not str or _INSTANT.fullmatch(text) is None:
        raise ValueError(
            "an instant is RFC 3339 with seconds, at most six fractional digits and an explicit "
            "Z or numeric offset; a stamp without a zone is refused, never read as UTC"
        )
    try:
        stamp = _dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise ValueError("the instant names a date or time that does not exist") from None
    return _in_utc(stamp)


#: The refusal of an instant whose UTC reading falls outside the years 0001 to 9999.
_NOT_IN_UTC = (
    "the instant cannot be stated in UTC: read in UTC it falls before 0001-01-01 or after "
    "9999-12-31, which no timestamp holds"
)


def _in_utc(stamp: _dt.datetime) -> _dt.datetime:
    """An aware datetime in UTC, or the fixed refusal.

    `0001-01-01T00:00:00+14:00` passes the instant grammar and names a real local time, and its
    UTC reading is a day before the first one a datetime holds, so `astimezone` raises
    `OverflowError` for it (2026-10-15); that escaped every caller that refuses a malformed
    instant by `ValueError`. A `ValueError` from a zone that states an impossible offset is
    refused the same way, and neither message repeats the instant.
    """
    try:
        return stamp.astimezone(_dt.timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError(_NOT_IN_UTC) from None


@dataclasses.dataclass(frozen=True)
class InjectedTime:
    """An instant a caller supplies and the basis on which it was resolved.

    The shape of `dis7.TimeContext` and `geojson.AsOf`, for every observation adapter: a time
    the payload does not state — a file-name slot, a product's publication date — is handed in
    as a constructor argument, so it is part of the determinism tuple, and its basis is recorded
    on what it reaches, because a time the caller supplied is a claim the caller made.
    """

    instant: _dt.datetime
    basis: str

    def __post_init__(self) -> None:
        if isinstance(self.instant, str):
            instant = parse_instant(self.instant)
        elif isinstance(self.instant, _dt.datetime) and self.instant.utcoffset() is not None:
            # `utcoffset()`, not `tzinfo`: a tzinfo whose offset is None is a naive datetime in
            # all but name, and `astimezone` would read it in the HOST's zone (R1b review F-3).
            instant = _in_utc(self.instant)
        else:
            raise ValueError("InjectedTime.instant is an RFC 3339 text or an aware datetime")
        object.__setattr__(self, "instant", instant)
        if type(self.basis) is not str or len(self.basis.strip()) < 8:
            raise ValueError("InjectedTime.basis says, in words, where the instant came from")
        if len(self.basis) > _BASIS_MAX:
            raise ValueError(f"InjectedTime.basis is longer than {_BASIS_MAX} characters")

    @property
    def rendered(self) -> str:
        return times.render(self.instant)


# -- the station table ---------------------------------------------------------------------------


class StationRow(_Block):
    station_id: Text
    lat: Annotated[float, Field(strict=True, ge=-90.0, le=90.0, allow_inf_nan=False)]
    lon: Annotated[float, Field(strict=True, ge=-180.0, le=180.0, allow_inf_nan=False)]


class StationTable(_Block):
    """Station positions the payload does not carry, supplied by the caller (a constructor
    argument, so a member of the determinism tuple). The adapter never joins two payloads to find
    a position: that would be fusion."""

    name: Text = Field(description="The table's own name, recorded in each position's basis.")
    basis: Text = Field(description="Where the table came from.")
    rows: list[StationRow] = Field(min_length=1)

    @field_validator("rows")
    @classmethod
    def _one_row_per_station(cls, rows: list[StationRow]) -> list[StationRow]:
        ids_ = [row.station_id for row in rows]
        if len(set(ids_)) != len(ids_):
            raise ValueError("a station appears twice in the table")
        return rows

    def position_of(self, station_id: str) -> tuple[float, float] | None:
        for row in self.rows:
            if row.station_id == station_id:
                return row.lat, row.lon
        return None


# -- constructor helpers -------------------------------------------------------------------------


def site_entity(
    *,
    source: SourceRef,
    system: str,
    station_id: str,
    site_class: str,
    valid_from: _dt.datetime,
    stated_position: tuple[float, float] | None = None,
    stated_position_basis: str | None = None,
    station_table: StationTable | None = None,
    status: OperationalStatus | None = None,
    stated_vertical: VerticalPosition | None = None,
    stated_vertical_basis: str | None = None,
) -> Entity:
    """The station, buoy, monitor or radar an observation names, as an `Entity`.

    Identity is `ids.derive(system, station_id)`. The position comes from the payload when it
    states one, else from the caller's station table, else it is `None` — never zeros — and its
    method is MANUAL (a surveyed site, not a fix), with the basis in `attributes`. `valid_from` is
    the observation instant, because that is when the source showed the site in this state.

    A height the payload states beside its position (a radar's site height, added 2026-10-15) is
    `stated_vertical`, carried as `Position.vertical` with the unit and datum the source names and
    its basis in `attributes.vertical_basis`; `alt_m` is set only when that is metres above the
    ellipsoid, which `Position` itself enforces. A height needs a stated position to sit on.
    """
    if stated_vertical is not None:
        if stated_position is None:
            raise ValueError("a stated height belongs to a position read from the payload")
        if not stated_vertical_basis or not stated_vertical_basis.strip():
            raise ValueError("a height read from the payload states where it was read")
    elif stated_vertical_basis is not None:
        raise ValueError("a vertical basis is stated and no height is")
    if site_class not in SITE_ENTITY_TYPES:
        raise ValueError(
            "the site class is not in SITE_ENTITY_TYPES; a new class is a row somebody adds"
        )
    if stated_position is not None:
        if not stated_position_basis or not stated_position_basis.strip():
            raise ValueError("a position read from the payload states where it was read")
        lat, lon = stated_position
        basis = stated_position_basis
    else:
        found = station_table.position_of(station_id) if station_table is not None else None
        if found is not None:
            lat, lon = found
            basis = f"station table {station_table.name}: {station_table.basis}"
        else:
            lat = lon = None
            basis = (
                "no position: the payload states none and no station table was supplied"
                if station_table is None
                else "no position: the payload states none and the station table has no row "
                "for this station"
            )
    position = None
    attributes = {"site_class": site_class, "position_basis": basis}
    if lat is not None:
        hae = (
            stated_vertical is not None
            and stated_vertical.reference is VerticalReference.HAE
            and stated_vertical.unit is VerticalUnit.METRES
        )
        position = Position(
            lat=lat,
            lon=lon,
            alt_m=stated_vertical.value if hae else None,
            position_source=PositionSource.MANUAL,
            vertical=stated_vertical,
        )
    if stated_vertical is not None:
        attributes["vertical_basis"] = stated_vertical_basis
    return Entity(
        source=source,
        source_ids=[SourceId(system=system, external_id=station_id)],
        entity_id=ids.derive(system, station_id),
        entity_type=SITE_ENTITY_TYPES[site_class],
        affiliation=Affiliation.UNKNOWN,
        position=position,
        valid_from=valid_from,
        status=status,
        attributes=attributes,
    )


def observation_event(
    *,
    source: SourceRef,
    source_ids: list[SourceId],
    observation: _Contract,
    observed_at: _dt.datetime,
    received_at: _dt.datetime,
    validity: TemporalValidity | None = None,
    related_entities: Sequence[uuid.UUID] = (),
    geometry: Geometry | None = None,
    quality: Quality | None = None,
    residual: Residual | None = None,
) -> Event:
    """The `ENVIRONMENTAL_OBSERVATION` Event carrying `observation`, with the `observed_at` rule
    checked rather than trusted.

    An observation's `observed_at` is the END of its sensing interval, which
    `validity.effective` states (an instant sets `end == start`); a model product's is the
    reference time its contract states, never the future instant the forecast is valid for.
    A `reference` product has no sensing instant and is not an Event (a `PlanObject` with an
    as-of carries it). A station or radar observation names its site in `related_entities`.
    The event's identity is derived from its first source identifier.
    """
    if not isinstance(observation, tuple(MODELS.values())):
        raise TypeError("observation is one of the four contract models")
    if not source_ids:
        raise ValueError("an observation event states the source identifier it is keyed on")
    if observation.product_class == "reference":
        raise ValueError(
            "a reference product states no sensing instant, so it is not an observation event"
        )
    # An aware instant whose UTC reading leaves 0001 to 9999 is the fixed refusal, never
    # `astimezone`'s `OverflowError` (R1b review F-2, 2026-10-15).
    if isinstance(observed_at, _dt.datetime) and observed_at.utcoffset() is not None:
        observed = _in_utc(observed_at)
    else:
        try:
            observed = times.parse(observed_at)
        except OverflowError:
            raise ValueError(_NOT_IN_UTC) from None
    if observation.product_class == "observation":
        effective = validity.effective if validity is not None else None
        if effective is None or effective.end is None:
            raise ValueError(
                "an observation states its sensing interval as validity.effective with an end"
            )
        if effective.end != observed:
            raise ValueError("an observation's observed_at is the end of its sensing interval")
    else:
        reference = observation.time.reference_time
        if reference is None:
            raise ValueError("a model product states its reference_time")
        if reference != observed:
            raise ValueError("a model product's observed_at is its reference_time")
    if isinstance(observation, (PointObservation, RadarSweep)) and not related_entities:
        raise ValueError("a station or radar observation names its site in related_entities")
    first = source_ids[0]
    return Event(
        source=source,
        source_ids=source_ids,
        event_id=ids.derive(first.system, first.external_id, kind="event"),
        event_type=EventType.ENVIRONMENTAL_OBSERVATION,
        severity=Severity.INFO,
        related_entities=list(related_entities),
        geometry=geometry,
        payload={PAYLOAD_KEY: observation.model_dump(mode="json")},
        observed_at=observed,
        received_at=received_at,
        validity=validity,
        quality=quality,
        residual=residual,
    )


# -- the MAPPINGS ledger -------------------------------------------------------------------------


def _unwrap(annotation: Any) -> list[Any]:
    """The concrete types an annotation admits, through Annotated, Optional and unions."""
    origin = typing.get_origin(annotation)
    if origin is Annotated:
        return _unwrap(typing.get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        found: list[Any] = []
        for arg in typing.get_args(annotation):
            found += _unwrap(arg)
        return found
    return [annotation]


def _resolves(annotation: Any, tokens: tuple) -> bool:
    if not tokens:
        return True
    head, rest = tokens[0], tokens[1:]
    for candidate in _unwrap(annotation):
        origin = typing.get_origin(candidate)
        if head is lossless.WILD or isinstance(head, int):
            if origin is list and _resolves(typing.get_args(candidate)[0], rest):
                return True
            continue
        if origin is dict:
            return True  # an opaque block: any key below is the source's own
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            fields = candidate.model_fields
            if head in fields and _resolves(fields[head].annotation, rest):
                return True
    return False


def contract_mapping(
    contract: str,
    field_path: str,
    *,
    rule: str = "identity",
    target: str = "event",
    tolerance: float | None = None,
    params: dict | None = None,
) -> lossless.Mapping:
    """One `MAPPINGS` destination inside a contract, refused if the contract has no such field.

    `field_path` is relative to the contract (`readings[*].measurement.value`); the destination
    is `<target>:payload.observation.<field_path>`. Checking the path against the model is the
    point: a ledger row naming a field the contract does not have would report every source leaf
    it covers as LOST, or worse, never be consulted.
    """
    if contract not in MODELS:
        raise ValueError("the contract is not one of the four")
    tokens = lossless.parse_path(field_path)
    if not tokens or not _resolves(MODELS[contract], tokens):
        raise ValueError("the field path names no field of the contract")
    return lossless.Mapping(
        f"{target}:payload.{PAYLOAD_KEY}.{field_path}", rule, tolerance, params or {}
    )


def ledger_rows(
    contract: str,
    rows: Mapping[str, str | tuple[str, str]],
    *,
    target: str = "event",
) -> dict[str, lossless.Mapping]:
    """`MAPPINGS` rows from source paths to contract fields: `{source: field}` or
    `{source: (field, rule)}`, each destination checked by `contract_mapping`."""
    built: dict[str, lossless.Mapping] = {}
    for source_path, destination in rows.items():
        field, rule = (destination, "identity") if isinstance(destination, str) else destination
        built[source_path] = contract_mapping(contract, field, rule=rule, target=target)
    return built


#: The `Limitation.id` every observation adapter declares for the arrays it leaves in the source.
BY_REFERENCE_LIMITATION = "values-by-reference"


def by_reference_limitation(source_paths: Iterable[str], *, notes: str | None = None) -> Limitation:
    """The structured limitation that makes the ledger classify uncopied arrays UNSUPPORTED.

    `source_paths` are paths in the parsed twin, in `lossless`'s spelling, of every array the
    contract carries by reference. Without this declaration (and a `MAPPINGS` ledger for it to
    reach) those leaves are LOST, which is what they would be.
    """
    paths = sorted(set(source_paths))
    if not paths:
        raise ValueError("a by-reference limitation names at least one source path")
    for path in paths:
        lossless.parse_path(path)
    return Limitation(
        id=BY_REFERENCE_LIMITATION,
        summary=(
            "Array values are carried by reference — a locator, the shape and packing needed to "
            "open them, and a summary — and are not copied into the output."
        ),
        unsupported_paths=paths,
        notes=notes,
    )


# -- publication ---------------------------------------------------------------------------------

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def file_stem(contract: str) -> str:
    """`gridded-field/1` -> `gridded-field-1`: the published file's stem."""
    return contract.replace("/", "-")


def generate() -> dict[str, dict]:
    """Every published contract schema, by file stem."""
    out: dict[str, dict] = {}
    for contract, model in MODELS.items():
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = DIALECT
        schema["$id"] = f"urn:synapsecommand:observation:{contract.replace('/', ':')}"
        schema["x-observation-contract"] = contract
        out[file_stem(contract)] = schema
    return out


def write(out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, schema in generate().items():
        path = out_dir / f"{stem}.schema.json"
        path.write_text(canonical.serialise(schema))
        written.append(path)
    return written


def check(out_dir: pathlib.Path) -> list[str]:
    """Paths missing, stale or not generated at all. Empty means the publication is current."""
    expected = generate()
    problems = []
    for stem, schema in expected.items():
        path = out_dir / f"{stem}.schema.json"
        if not path.is_file():
            problems.append(f"{path}: missing")
        elif path.read_text() != canonical.serialise(schema):
            problems.append(f"{path}: stale — the contract models changed; re-export")
    if out_dir.is_dir():
        for path in sorted(out_dir.glob("*.schema.json")):
            if path.name.removesuffix(".schema.json") not in expected:
                problems.append(f"{path}: not a contract this module publishes")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m synapse_cdm.observation_contracts",
        description="Write or check the observation contracts' published JSON Schemas.",
    )
    parser.add_argument("--out", default="schemas/observation", type=pathlib.Path)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the files are missing or stale"
    )
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{'STALE' if problems else 'CURRENT'}: {args.out} vs {', '.join(CONTRACTS)}")
        return 1 if problems else 0
    for path in write(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
