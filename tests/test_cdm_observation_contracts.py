"""The four observation payload contracts and the helpers every observation adapter builds with.

`synapse_cdm.observation_contracts` (added 2026-10-15). Every block is
given a valid literal and each refusal its whole outcome — the location, the error type and the
message — written by hand; the discriminators are driven through every tag and one that is not
one; the published schemas under `schemas/observation/` are held to the models and shown to
validate the same literals; and the shared test support in `tests/observation_support.py` is
exercised here, once, on fixture trees written under `tmp_path`.

Repository-bound: it reads `schemas/observation/` at the repository root, which the wheel does not
carry. Nothing below is compared with output the code under test produced: identifiers are
derived with the standard library's `uuid.uuid5` from the namespace `ids.py` documents, digests
with `hashlib`, and every other expectation is a literal.
"""

import copy
import datetime as dt
import json
import pathlib
import subprocess
import sys
import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from synapse_cdm import lossless
from synapse_cdm import observation_contracts as oc
from synapse_cdm.enums import EventType
from synapse_cdm.evidence import PROVENANCE_SCHEMA_ID
from synapse_cdm.manifest import LimitKind
from synapse_cdm.models import Event, OperationalStatus, SourceId, SourceRef, TemporalValidity
from synapse_cdm.schemas import validator_for
from tests import observation_support as support

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "schemas" / "observation"

#: `ids.NAMESPACE`, typed out from the module's own documentation rather than imported.
ID_NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")

UTC_SOURCE = {"name": "UTC", "stated_by": "source", "basis": "the format states UTC"}

GRIDDED = {
    "contract": "gridded-field/1",
    "product_class": "forecast",
    "product_version": {"run": "t12z", "production_time_verbatim": "20260911T1305Z"},
    "time": {
        "source_time_system": UTC_SOURCE,
        "reference_time": "2026-09-11T12:00:00.000Z",
        "reference_time_significance": {
            "code": "1",
            "namespace": "GRIB2 Table 1.2",
            "meaning": "Start of forecast",
        },
        "forecast_offset": {"value": 1, "unit": "hour", "unit_namespace": "GRIB2 Table 4.4"},
        "statistical_process": {"code": "1", "namespace": "GRIB2 Table 4.10"},
    },
    "locator": {"kind": "grib", "message": 3, "field": 0, "byte_offset": 1024},
    "quality_flags_basis": "the message carries no bit-map",
    "quantity": {"name": "APCP", "code": "0.1.8", "namespace": "GRIB2 Table 4.2"},
    "unit": {"unit": "kg m-2", "unit_namespace": "GRIB2 Table 4.2"},
    "level": {"type": "Ground or water surface", "code": "1", "namespace": "GRIB2 Table 4.5"},
    "grid": {
        "namespace": "GRIB2 Table 3.1",
        "template": "3.30",
        "shape": [4, 5],
        "scanning_mode": "01000000",
        "cell_size": [
            {"value": 3000, "unit": "m", "unit_namespace": "GRIB2 template 3.30"},
            {"value": 3000, "unit": "m", "unit_namespace": "GRIB2 template 3.30"},
        ],
        "parameters": {"La1": 56.5, "Lo1": 20.5, "LoV": 22.0, "Latin1": 57.0},
    },
    "values": {
        "mode": "reference",
        "locator": {"kind": "grib", "message": 3, "field": 0, "byte_offset": 1024},
        "shape": [4, 5],
        "dtype": "float32",
        "encoding": "GRIB2 template 5.3",
        "summary": {"count": 20, "missing_count": 2, "min": 0.0, "max": 1.5},
    },
}

POINT = {
    "contract": "point-observation/1",
    "product_class": "observation",
    "time": {"source_time_system": UTC_SOURCE},
    "locator": {"kind": "table", "row": 0, "header_lines": 2},
    "quality_flags_basis": "the format publishes no per-value flags",
    "station_id": "EX001",
    "station_namespace": "synthetic five-character station block",
    "readings": [
        {
            "name": "WSPD",
            "namespace": "header line 1",
            "measurement": {"value": 6.2, "unit": "m/s", "unit_namespace": "header line 2"},
        },
        {
            "name": "GST",
            "namespace": "header line 1",
            "absence": {
                "cause": "sentinel",
                "mechanism": "the format's missing-value marker",
                "sentinel": "MM",
            },
        },
    ],
}

RADAR = {
    "contract": "radar-sweep/1",
    "product_class": "observation",
    "time": {"source_time_system": UTC_SOURCE},
    "locator": {"kind": "radar", "ldm_record": 1, "message": 0, "elevation_number": 1},
    "quality_flags": [
        {"name": "below_threshold", "value": 17, "namespace": "moment code 0", "applies_to": "REF"},
        {"name": "range_folded", "value": 3, "namespace": "moment code 1", "applies_to": "REF"},
    ],
    "site_id": "ZZZZ",
    "elevation_number": 1,
    "elevation_angle": {"value": 0.5, "unit": "deg", "unit_namespace": "elevation angle field"},
    "radial_count": 720,
    "coverage_pattern": {"code": "212", "namespace": "volume coverage pattern"},
    "moments": [
        {
            "name": "REF",
            "namespace": "moment block name",
            "unit": {"unit": "dBZ", "unit_namespace": "moment block"},
            "gate_count": 1832,
            "first_gate_range": {"value": 2.125, "unit": "km", "unit_namespace": "moment block"},
            "gate_interval": {"value": 0.25, "unit": "km", "unit_namespace": "moment block"},
            "values": {
                "mode": "reference",
                "locator": {
                    "kind": "radar",
                    "ldm_record": 1,
                    "message": 0,
                    "elevation_number": 1,
                    "moment": "REF",
                },
                "shape": [720, 1832],
                "dtype": "uint8",
                "encoding": "bzip2 record",
                "scale": 2.0,
                "offset": 66.0,
            },
        }
    ],
}

IMAGERY = {
    "contract": "imagery-product/1",
    "product_class": "observation",
    "product_version": {"version": "v2.0"},
    "time": {"source_time_system": UTC_SOURCE},
    "locator": {"kind": "raster", "band_file": "EX_TILE_B04.tif", "granule_id": "EX_GRANULE"},
    "quality_flags_basis": "the band file carries no per-pixel flags",
    "product": {"name": "surface reflectance", "namespace": "synthetic product list"},
    "band": {"name": "B04", "namespace": "synthetic band list"},
    "unit": {"unit": "1", "unit_namespace": "band metadata"},
    "values": {
        "mode": "inline",
        "shape": [2, 2],
        "values": [0.1, 0.2, None, 0.4],
        "missing_mechanism": "the band's fill value -9999",
    },
}

LITERALS = {
    "gridded-field/1": GRIDDED,
    "point-observation/1": POINT,
    "radar-sweep/1": RADAR,
    "imagery-product/1": IMAGERY,
}


def _errors(model, doc) -> list[tuple[tuple, str, str]]:
    """(loc, type, msg) of every finding on the Python path, sorted; [] when accepted."""
    try:
        (model.validate_python if isinstance(model, TypeAdapter) else model.model_validate)(doc)
    except ValidationError as e:
        return sorted((err["loc"], err["type"], err["msg"]) for err in e.errors())
    return []


def _schema(contract: str) -> dict:
    return json.loads((PUBLISHED / f"{contract.replace('/', '-')}.schema.json").read_text())


def _schema_errors(contract: str, doc) -> list[tuple[str, str, str]]:
    return sorted(
        ("/".join(str(p) for p in e.absolute_path), e.validator, e.message)
        for e in validator_for(_schema(contract)).iter_errors(doc)
    )


def with_(doc: dict, **changes) -> dict:
    out = copy.deepcopy(doc)
    out.update(copy.deepcopy(changes))
    return out


# -- the four literals ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract", oc.CONTRACTS)
def test_each_contract_literal_is_accepted_and_dumps_back_to_itself(contract):
    doc = LITERALS[contract]
    model = oc.MODELS[contract].model_validate(doc)
    assert model.contract == contract
    assert model.model_dump(mode="json", exclude_defaults=True) == doc


@pytest.mark.parametrize("contract", oc.CONTRACTS)
def test_the_published_schema_validates_the_literal_and_its_full_dump(contract):
    doc = LITERALS[contract]
    assert _schema_errors(contract, doc) == []
    assert (
        _schema_errors(contract, oc.MODELS[contract].model_validate(doc).model_dump(mode="json"))
        == []
    )


@pytest.mark.parametrize("contract", oc.CONTRACTS)
def test_the_published_schema_refuses_an_unknown_key_as_the_model_does(contract):
    doc = with_(LITERALS[contract], crs="EPSG:4326")
    assert _schema_errors(contract, doc) == [
        ("", "additionalProperties", "Additional properties are not allowed ('crs' was unexpected)")
    ]
    assert _errors(oc.MODELS[contract], doc) == [
        (("crs",), "extra_forbidden", "Extra inputs are not permitted")
    ]


def test_the_contract_names_and_the_payload_key():
    assert oc.CONTRACTS == (
        "gridded-field/1",
        "point-observation/1",
        "radar-sweep/1",
        "imagery-product/1",
    )
    assert list(oc.MODELS) == list(oc.CONTRACTS)
    assert oc.PAYLOAD_KEY == "observation"
    assert oc.MODEL_PRODUCT_CLASSES == ("forecast", "analysis", "reanalysis", "modelled_estimate")


# -- the discriminators --------------------------------------------------------------------------


@pytest.mark.parametrize("contract", oc.CONTRACTS)
def test_the_contract_name_selects_the_model(contract):
    assert type(oc.parse_observation(LITERALS[contract])) is oc.MODELS[contract]


def test_a_contract_name_that_is_not_one_of_the_four_is_refused():
    assert _errors(oc._CONTRACT_ADAPTER, with_(POINT, contract="point-observation/2")) == [
        (
            (),
            "union_tag_invalid",
            "Input tag 'point-observation/2' found using 'contract' does not match any of the "
            "expected tags: 'gridded-field/1', 'point-observation/1', 'radar-sweep/1', "
            "'imagery-product/1'",
        )
    ]


def test_a_values_mode_and_a_locator_kind_that_are_not_declared_are_refused():
    values = with_(GRIDDED["values"], mode="copy")
    assert _errors(oc.GriddedField, with_(GRIDDED, values=values)) == [
        (
            ("values",),
            "union_tag_invalid",
            "Input tag 'copy' found using 'mode' does not match any of the expected tags: "
            "'reference', 'inline'",
        )
    ]
    assert _errors(TypeAdapter(oc.Locator), {"kind": "zip", "member": "a"}) == [
        (
            (),
            "union_tag_invalid",
            "Input tag 'zip' found using 'kind' does not match any of the expected tags: 'grib', "
            "'radar', 'table', 'raster', 'parquet', 'netcdf', 'hdf5'",
        )
    ]


@pytest.mark.parametrize(
    "locator, cls",
    [
        ({"kind": "grib", "message": 0, "field": 1, "byte_offset": 0}, oc.GribLocator),
        ({"kind": "radar", "ldm_record": 0, "message": 2, "elevation_number": 3}, oc.RadarLocator),
        ({"kind": "table", "row": 4, "header_lines": 0}, oc.TableLocator),
        (
            {"kind": "raster", "window": {"column": 0, "row": 0, "width": 2, "height": 2}},
            oc.RasterLocator,
        ),
        ({"kind": "parquet", "row_group": 1, "row": 7}, oc.ParquetLocator),
        ({"kind": "netcdf", "group": "/", "variable": "Rad", "index": [0, 3]}, oc.ArrayLocator),
        ({"kind": "hdf5", "group": "/Grid", "variable": "precipitation"}, oc.ArrayLocator),
    ],
    ids=["grib", "radar", "table", "raster", "parquet", "netcdf", "hdf5"],
)
def test_every_locator_kind_selects_its_model(locator, cls):
    parsed = TypeAdapter(oc.Locator).validate_python(locator)
    assert type(parsed) is cls
    assert parsed.kind == locator["kind"]


# -- refusals, block by block --------------------------------------------------------------------

MEASUREMENT = {"value": 6.2, "unit": "m/s", "unit_namespace": "header line 2"}


@pytest.mark.parametrize(
    "doc, expected",
    [
        (
            with_(MEASUREMENT, value="6.2"),
            [(("value",), "float_type", "Input should be a valid number")],
        ),
        (
            with_(MEASUREMENT, value=True),
            [(("value",), "float_type", "Input should be a valid number")],
        ),
        (
            with_(MEASUREMENT, value=float("nan")),
            [(("value",), "finite_number", "Input should be a finite number")],
        ),
        (
            {"value": 6.2, "unit_namespace": "header line 2"},
            [(("unit",), "missing", "Field required")],
        ),
        (
            with_(MEASUREMENT, unit=""),
            [(("unit",), "string_too_short", "String should have at least 1 character")],
        ),
        (
            with_(MEASUREMENT, unit="  "),
            [
                (
                    ("unit",),
                    "value_error",
                    "Value error, the text is blank; a blank string states nothing",
                )
            ],
        ),
        (
            with_(MEASUREMENT, unit=1),
            [(("unit",), "string_type", "Input should be a valid string")],
        ),
        (
            with_(MEASUREMENT, scale=0.1),
            [(("scale",), "extra_forbidden", "Extra inputs are not permitted")],
        ),
    ],
    ids=["text", "bool", "nan", "no-unit", "empty-unit", "blank-unit", "unit-number", "extra"],
)
def test_a_measurement_states_a_finite_value_and_a_unit_or_is_refused(doc, expected):
    assert _errors(oc.Measurement, doc) == expected


@pytest.mark.parametrize(
    "doc, expected",
    [
        ({"cause": "sentinel", "mechanism": "the missing-value marker", "sentinel": "MM"}, []),
        ({"cause": "unit_unknown", "mechanism": "no units line in this file version"}, []),
        (
            {"cause": "sentinel", "mechanism": "the missing-value marker"},
            [
                (
                    (),
                    "value_error",
                    "Value error, a sentinel absence states the marker the source wrote",
                )
            ],
        ),
        (
            {"cause": "unit_unknown", "mechanism": "no units line", "sentinel": "99.0"},
            [
                (
                    (),
                    "value_error",
                    "Value error, a unit_unknown absence carries no marker: the unreadable value "
                    "belongs in the residual, never beside a contract field that says it is not "
                    "stated",
                )
            ],
        ),
        (
            {"cause": "withheld", "mechanism": "x"},
            [(("cause",), "literal_error", "Input should be 'sentinel' or 'unit_unknown'")],
        ),
    ],
    ids=["sentinel", "unit-unknown", "sentinel-without-marker", "unknown-with-marker", "cause"],
)
def test_an_absence_names_its_mechanism_and_carries_a_marker_only_for_a_sentinel(doc, expected):
    assert _errors(oc.Absence, doc) == expected


@pytest.mark.parametrize(
    "model, doc, expected",
    [
        (
            oc.Quantity,
            {"namespace": "GRIB2 Table 4.2"},
            [((), "value_error", "Value error, a quantity states a name, a code or both")],
        ),
        (
            oc.VerticalLevel,
            {"value": 500, "unit": "hPa", "namespace": "GRIB2 Table 4.5"},
            [((), "value_error", "Value error, a level states its type, its code or both")],
        ),
        (
            oc.VerticalLevel,
            {"code": "100", "value": 500, "namespace": "GRIB2 Table 4.5"},
            [
                (
                    (),
                    "value_error",
                    "Value error, a level value without a unit is not stated: carry neither",
                )
            ],
        ),
        (
            oc.VerticalLevel,
            {"code": "100", "unit": "hPa", "namespace": "GRIB2 Table 4.5"},
            [((), "value_error", "Value error, a level unit without a value states nothing")],
        ),
        (
            oc.Datum,
            {"name": "NAVD88"},
            [(("namespace",), "missing", "Field required")],
        ),
    ],
    ids=[
        "quantity-unnamed",
        "level-untyped",
        "level-value-no-unit",
        "level-unit-no-value",
        "datum-no-namespace",
    ],
)
def test_quantities_levels_and_datums_are_refused_when_they_state_too_little(model, doc, expected):
    assert _errors(model, doc) == expected


GRID = GRIDDED["grid"]


@pytest.mark.parametrize(
    "doc, expected",
    [
        (
            with_(GRID, parameters={"projection": {"CRS": "EPSG:4326"}}),
            [
                (
                    (),
                    "value_error",
                    "Value error, the grid's parameters hold parameters.projection.CRS: a crs "
                    "key. There is no crs field and there will not be one: the adapter converts "
                    "to WGS84 for Event.geometry, and every number in a contract is finite",
                )
            ],
        ),
        (
            with_(GRID, parameters={"Lo1": float("inf")}),
            [
                (
                    (),
                    "value_error",
                    "Value error, the grid's parameters hold parameters.Lo1: a non-finite "
                    "number. There is no crs field and there will not be one: the adapter "
                    "converts to WGS84 for Event.geometry, and every number in a contract is "
                    "finite",
                )
            ],
        ),
        (
            with_(GRID, crs="EPSG:4326"),
            [(("crs",), "extra_forbidden", "Extra inputs are not permitted")],
        ),
        (
            with_(GRID, cell_size=GRID["cell_size"][:1]),
            [((), "value_error", "Value error, cell_size states one size per axis of shape")],
        ),
        (
            with_(GRID, shape=[]),
            [
                (
                    ("shape",),
                    "too_short",
                    "List should have at least 1 item after validation, not 0",
                )
            ],
        ),
        (
            with_(GRID, shape=[4, 0], cell_size=None),
            [(("shape", 1), "greater_than_equal", "Input should be greater than or equal to 1")],
        ),
    ],
    ids=["nested-crs", "non-finite", "top-crs", "cell-size-count", "no-axis", "zero-axis"],
)
def test_a_grid_has_no_crs_key_at_any_depth_and_one_size_per_axis(doc, expected):
    assert _errors(oc.Grid, doc) == expected


@pytest.mark.parametrize(
    "doc, expected",
    [
        (
            {"kind": "raster"},
            [
                (
                    ("raster",),
                    "value_error",
                    "Value error, a raster locator names a band file, an IFD, a tile or a window",
                )
            ],
        ),
        (
            {"kind": "grib", "message": -1, "field": 0, "byte_offset": 0},
            [
                (
                    ("grib", "message"),
                    "greater_than_equal",
                    "Input should be greater than or equal to 0",
                )
            ],
        ),
        (
            {"kind": "grib", "message": True, "field": 0, "byte_offset": 0},
            [(("grib", "message"), "int_type", "Input should be a valid integer")],
        ),
        (
            {"kind": "radar", "ldm_record": 0, "message": 0, "elevation_number": 0},
            [
                (
                    ("radar", "elevation_number"),
                    "greater_than_equal",
                    "Input should be greater than or equal to 1",
                )
            ],
        ),
        (
            {"kind": "table", "row": 0, "header_lines": 1, "frame_sha256": "AB" * 32},
            [
                (
                    ("table", "frame_sha256"),
                    "string_pattern_mismatch",
                    "String should match pattern '^[0-9a-f]{64}$'",
                )
            ],
        ),
        (
            {"kind": "netcdf", "group": "Grid", "variable": "x"},
            [
                (
                    ("netcdf", "group"),
                    "string_pattern_mismatch",
                    "String should match pattern '^/'",
                )
            ],
        ),
    ],
    ids=[
        "raster-nowhere",
        "negative-ordinal",
        "bool-ordinal",
        "elevation-zero",
        "upper-digest",
        "relative-group",
    ],
)
def test_a_locator_is_refused_when_it_points_nowhere_or_its_ordinals_are_not_ordinals(
    doc, expected
):
    assert _errors(TypeAdapter(oc.Locator), doc) == expected


def test_a_frame_digest_and_a_granule_id_ride_on_any_locator():
    digest = "0123456789abcdef" * 4
    parsed = TypeAdapter(oc.Locator).validate_python(
        {"kind": "parquet", "row_group": 0, "row": 0, "frame_sha256": digest, "granule_id": "G1"}
    )
    assert (parsed.frame_sha256, parsed.granule_id) == (digest, "G1")


SUMMARY = {"count": 20, "missing_count": 2, "min": 0.0, "max": 1.5}


@pytest.mark.parametrize(
    "doc, expected",
    [
        ({"count": 4, "missing_count": 4}, []),
        (
            with_(SUMMARY, missing_count=21),
            [((), "value_error", "Value error, missing_count exceeds count")],
        ),
        (
            {"count": 4, "missing_count": 0, "min": 1.0},
            [((), "value_error", "Value error, min and max are stated together or not at all")],
        ),
        (
            with_(SUMMARY, min=2.0),
            [((), "value_error", "Value error, min exceeds max")],
        ),
        (
            {"count": 4, "missing_count": 4, "min": 1.0, "max": 1.0},
            [((), "value_error", "Value error, an array with no stated value has no min or max")],
        ),
    ],
    ids=["all-missing", "missing-past-count", "min-alone", "min-past-max", "extremes-of-nothing"],
)
def test_an_array_summary_is_consistent_or_refused(doc, expected):
    assert _errors(oc.ArraySummary, doc) == expected


def test_a_reference_summary_counts_the_cells_its_shape_describes():
    values = with_(GRIDDED["values"], summary=with_(SUMMARY, count=21))
    assert _errors(oc.ValuesByReference, values) == [
        ((), "value_error", "Value error, summary.count is not the number of cells shape describes")
    ]


INLINE = IMAGERY["values"]


@pytest.mark.parametrize(
    "doc, expected",
    [
        (
            with_(INLINE, shape=[2, 3]),
            [
                (
                    (),
                    "value_error",
                    "Value error, the number of values is not the number of cells shape describes",
                )
            ],
        ),
        (
            {"mode": "inline", "shape": [2], "values": [1.0, None]},
            [((), "value_error", "Value error, a missing value needs its missing_mechanism")],
        ),
        (
            {"mode": "inline", "shape": [2], "values": [1.0, 2.0], "missing_mechanism": "fill"},
            [
                (
                    (),
                    "value_error",
                    "Value error, missing_mechanism is stated and no value is missing",
                )
            ],
        ),
    ],
    ids=["shape", "missing-without-mechanism", "mechanism-without-missing"],
)
def test_inline_values_match_their_shape_and_name_what_made_a_value_missing(doc, expected):
    assert _errors(oc.ValuesInline, doc) == expected


def test_inline_values_stop_at_the_cap():
    assert oc.MAX_INLINE_VALUES == 4096
    at_the_cap = {"mode": "inline", "shape": [64, 64], "values": [0.5] * 4096}
    assert _errors(oc.ValuesInline, at_the_cap) == []
    past_it = {"mode": "inline", "shape": [4097], "values": [0.5] * 4097}
    assert _errors(oc.ValuesInline, past_it) == [
        (
            ("values",),
            "too_long",
            "List should have at most 4096 items after validation, not 4097",
        )
    ]
    basis = oc.MAX_INLINE_VALUES_BASIS
    assert basis.kind is LimitKind.IMPLEMENTATION_CAP
    assert "1799 x 1059" in basis.source and "512 x 512" in basis.source
    assert basis.test == (
        "tests/test_cdm_observation_contracts.py::test_inline_values_stop_at_the_cap"
    )


@pytest.mark.parametrize(
    "contract, change, expected",
    [
        (
            "gridded-field/1",
            {"unit": None, "values": INLINE},
            [
                (
                    (),
                    "value_error",
                    "Value error, the field carries inline values and no unit: a value whose "
                    "unit is not stated is not stated",
                )
            ],
        ),
        (
            "imagery-product/1",
            {"unit": None},
            [
                (
                    (),
                    "value_error",
                    "Value error, the product carries inline values and no unit: a value whose "
                    "unit is not stated is not stated",
                )
            ],
        ),
        (
            "point-observation/1",
            {"quality_flags_basis": None},
            [
                (
                    (),
                    "value_error",
                    "Value error, no quality flag and no quality_flags_basis: an empty list "
                    "reads as 'nothing was wrong', so the absence is stated with its reason",
                )
            ],
        ),
        (
            "radar-sweep/1",
            {"quality_flags_basis": "none set"},
            [
                (
                    (),
                    "value_error",
                    "Value error, quality_flags_basis states an absence and flags are present",
                )
            ],
        ),
        (
            "point-observation/1",
            {"readings": [POINT["readings"][0], POINT["readings"][0]]},
            [
                (
                    (),
                    "value_error",
                    "Value error, a reading is stated twice for one name, namespace and level",
                )
            ],
        ),
        (
            "point-observation/1",
            {"readings": [with_(POINT["readings"][0], absence=POINT["readings"][1]["absence"])]},
            [
                (
                    ("readings", 0),
                    "value_error",
                    "Value error, a reading states a measurement or an absence, exactly one",
                )
            ],
        ),
        (
            "point-observation/1",
            {"readings": []},
            [
                (
                    ("readings",),
                    "too_short",
                    "List should have at least 1 item after validation, not 0",
                )
            ],
        ),
        (
            "radar-sweep/1",
            {"locator": {"kind": "table", "row": 0, "header_lines": 0}},
            [((), "value_error", "Value error, a radar sweep is located by a radar locator")],
        ),
        (
            "radar-sweep/1",
            {"elevation_number": 2},
            [
                (
                    (),
                    "value_error",
                    "Value error, the locator names another elevation than the sweep's",
                )
            ],
        ),
        (
            "radar-sweep/1",
            {"moments": RADAR["moments"] * 2},
            [((), "value_error", "Value error, a moment is stated twice")],
        ),
        (
            "gridded-field/1",
            {"product_class": "nowcast"},
            [
                (
                    ("product_class",),
                    "literal_error",
                    "Input should be 'observation', 'forecast', 'analysis', 'reanalysis', "
                    "'modelled_estimate' or 'reference'",
                )
            ],
        ),
        (
            "gridded-field/1",
            {"product_version": {}},
            [
                (
                    ("product_version",),
                    "value_error",
                    "Value error, an empty product_version is the absence of one: omit it",
                )
            ],
        ),
        (
            "gridded-field/1",
            {"time": {"source_time_system": UTC_SOURCE, "forecast_offset": MEASUREMENT}},
            [
                (
                    ("time",),
                    "value_error",
                    "Value error, a significance or a forecast offset qualifies a reference_time",
                )
            ],
        ),
        (
            "point-observation/1",
            {"time": {"source_time_system": with_(UTC_SOURCE, stated_by="guess")}},
            [
                (
                    ("time", "source_time_system", "stated_by"),
                    "literal_error",
                    "Input should be 'source' or 'caller'",
                )
            ],
        ),
        (
            "point-observation/1",
            {"time": {}},
            [(("time", "source_time_system"), "missing", "Field required")],
        ),
    ],
    ids=[
        "field-inline-no-unit",
        "product-inline-no-unit",
        "no-flags-no-basis",
        "flags-and-basis",
        "reading-twice",
        "reading-both",
        "no-reading",
        "radar-located-by-row",
        "other-elevation",
        "moment-twice",
        "product-class",
        "empty-version",
        "orphan-offset",
        "time-system-guessed",
        "no-time-system",
    ],
)
def test_a_contract_is_refused_where_it_would_state_something_it_cannot(contract, change, expected):
    assert _errors(oc.MODELS[contract], with_(LITERALS[contract], **change)) == expected


#: The reference time on the Python path, which `parse_observation` and `contract_of` take. The
#: CDM's own `Timestamp` reads a naive string as UTC there and lets a non-string reach `.strip()`;
#: a contract that exists to state its time system takes an aware datetime or the wire form only.
REFERENCE_TIME_REFUSED = (
    "Value error, reference_time is an aware datetime or the wire form "
    "2026-04-29T06:12:44.000Z; a stamp without a zone is refused, never read as UTC"
)


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-11T12:00:00",
        "2026-09-11",
        "2026-09-11T12:00:00Z",
        "2026-09-11T14:00:00+02:00",
        " 2026-09-11T12:00:00.000Z",
        1789000000,
        True,
        [1],
        {},
        dt.datetime(2026, 9, 11, 12, 0),
    ],
    ids=[
        "naive",
        "date-only",
        "no-millis",
        "offset-text",
        "padded",
        "int",
        "bool",
        "list",
        "dict",
        "naive-datetime",
    ],
)
def test_a_reference_time_without_its_zone_or_not_a_stamp_is_refused_on_the_python_path(value):
    doc = copy.deepcopy(GRIDDED)
    doc["time"]["reference_time"] = value
    expected = [(("time", "reference_time"), "value_error", REFERENCE_TIME_REFUSED)]
    assert _errors(oc.GriddedField, doc) == expected
    assert _errors(oc._CONTRACT_ADAPTER, doc) == [
        (("gridded-field/1",) + loc, t, m) for loc, t, m in expected
    ]


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-11T12:00:00.000Z",
        dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 9, 11, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=2))),
    ],
    ids=["wire", "utc-datetime", "offset-datetime"],
)
def test_a_reference_time_is_an_aware_datetime_or_the_wire_form(value):
    doc = copy.deepcopy(GRIDDED)
    doc["time"]["reference_time"] = value
    model = oc.parse_observation(doc)
    assert model.time.reference_time == dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
    assert model.model_dump(mode="json")["time"]["reference_time"] == "2026-09-11T12:00:00.000Z"


#: An aware datetime at either end of the range whose UTC reading leaves it (checkpoint H-02).
_PLUS_14 = dt.timezone(dt.timedelta(hours=14))
_MINUS_14 = dt.timezone(dt.timedelta(hours=-14))
DATETIMES_PAST_UTC = [
    dt.datetime(1, 1, 1, 0, 0, tzinfo=_PLUS_14),
    dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=_MINUS_14),
]


@pytest.mark.parametrize(
    "value", DATETIMES_PAST_UTC, ids=["first-day-plus-14", "last-day-minus-14"]
)
def test_a_reference_time_utc_cannot_state_is_a_validation_error(value):
    doc = copy.deepcopy(GRIDDED)
    doc["time"]["reference_time"] = value
    assert _errors(oc.GriddedField, doc) == [
        (
            ("time", "reference_time"),
            "value_error",
            "Value error, a timestamp read in UTC falls before 0001-01-01 or after 9999-12-31, "
            "which no timestamp holds; the value is not repeated here",
        )
    ]


def test_the_json_path_keeps_the_wire_rule_for_a_reference_time():
    doc = copy.deepcopy(GRIDDED)
    doc["time"]["reference_time"] = "2026-09-11T12:00:00"
    with pytest.raises(ValidationError) as caught:
        oc.GriddedField.model_validate_json(json.dumps(doc))
    assert [(e["loc"], e["type"], e["msg"]) for e in caught.value.errors()] == [
        (("time", "reference_time"), "value_error", REFERENCE_TIME_REFUSED)
    ]
    accepted = oc.GriddedField.model_validate_json(json.dumps(GRIDDED))
    assert accepted.time.reference_time == dt.datetime(2026, 9, 11, 12, tzinfo=dt.timezone.utc)


#: What the published schemas cannot hold. JSON Schema states shape, enumerations, patterns and
#: closed objects; the models also hold cross-field rules, non-blank text and finite numbers.
#: Each document below passes its published schema and is refused by its model, and the
#: documentation names these three classes (`observation-contracts.mdx`, ADR 0012).
SCHEMA_IS_LOOSER = [
    (
        "point-observation/1",
        {"station_id": "   "},
        [
            (
                ("station_id",),
                "value_error",
                "Value error, the text is blank; a blank string states nothing",
            )
        ],
    ),
    (
        "imagery-product/1",
        {"unit": None},
        [
            (
                (),
                "value_error",
                "Value error, the product carries inline values and no unit: a value whose "
                "unit is not stated is not stated",
            )
        ],
    ),
    (
        "point-observation/1",
        {"quality_flags_basis": None},
        [
            (
                (),
                "value_error",
                "Value error, no quality flag and no quality_flags_basis: an empty list "
                "reads as 'nothing was wrong', so the absence is stated with its reason",
            )
        ],
    ),
    (
        "radar-sweep/1",
        {"elevation_number": 2},
        [
            (
                (),
                "value_error",
                "Value error, the locator names another elevation than the sweep's",
            )
        ],
    ),
    (
        "point-observation/1",
        {
            "readings": [
                with_(
                    POINT["readings"][0],
                    measurement=with_(MEASUREMENT, value=float("inf")),
                )
            ]
        },
        [
            (
                ("readings", 0, "measurement", "value"),
                "finite_number",
                "Input should be a finite number",
            )
        ],
    ),
]


@pytest.mark.parametrize(
    "contract, change, expected",
    SCHEMA_IS_LOOSER,
    ids=[
        "blank-text",
        "cross-field-unit",
        "cross-field-flags",
        "cross-field-elevation",
        "infinite",
    ],
)
def test_the_published_schema_holds_less_than_the_model_and_the_classes_are_named(
    contract, change, expected
):
    doc = with_(LITERALS[contract], **change)
    assert _schema_errors(contract, doc) == []
    assert _errors(oc.MODELS[contract], doc) == expected


def test_the_documentation_names_what_the_schema_cannot_hold():
    sentence = (
        "the published schemas hold shape, enumerations, patterns and closed objects, not the "
        "models' cross-field rules, non-blank text or finite numbers"
    )
    for page in (
        REPO / "docs" / "docs" / "cdm" / "observation-contracts.mdx",
        REPO / "docs" / "adr" / "0012-observation-contracts.md",
    ):
        assert sentence in " ".join(page.read_text(encoding="utf-8").split())


def test_a_quality_flag_value_is_verbatim_and_its_type_is_kept():
    flags = [
        {"name": "q", "value": "p", "namespace": "verbatim", "applies_to": "record"},
        {"name": "n", "value": 3, "namespace": "verbatim", "applies_to": "record"},
        {"name": "b", "value": False, "namespace": "verbatim", "applies_to": "record"},
        {"name": "f", "value": 0.75, "namespace": "verbatim", "applies_to": "record"},
    ]
    parsed = oc.PointObservation.model_validate(
        with_(POINT, quality_flags=flags, quality_flags_basis=None)
    )
    assert [(type(f.value), f.value) for f in parsed.quality_flags] == [
        (str, "p"),
        (int, 3),
        (bool, False),
        (float, 0.75),
    ]


# -- the published schemas -----------------------------------------------------------------------


def _property_names(node, found=None) -> set[str]:
    found = set() if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found |= set(value)
            _property_names(value, found)
    elif isinstance(node, list):
        for item in node:
            _property_names(item, found)
    return found


def _object_schemas(node):
    if isinstance(node, dict):
        if "properties" in node:
            yield node
        for value in node.values():
            yield from _object_schemas(value)
    elif isinstance(node, list):
        for item in node:
            yield from _object_schemas(item)


@pytest.mark.parametrize("contract", oc.CONTRACTS)
def test_no_key_in_a_contract_schema_ends_at_and_no_key_is_crs(contract):
    names = _property_names(_schema(contract))
    assert sorted(n for n in names if n.endswith("_at")) == []
    # `applies_to` is the one key ending in a time suffix, and it names what a flag covers:
    # a reading, a moment or `record`, never an instant.
    assert sorted(n for n in names if n.endswith(("_from", "_to"))) == ["applies_to"]
    assert "crs" not in {n.casefold() for n in names}
    assert all(s.get("additionalProperties") is False for s in _object_schemas(_schema(contract)))


def test_product_version_holds_processing_facts_and_no_time_key():
    block = _schema("gridded-field/1")["$defs"]["ProductVersion"]["properties"]
    assert sorted(block) == ["producer", "production_time_verbatim", "run", "version"]


def test_the_publication_is_the_four_files_the_models_generate():
    assert sorted(p.name for p in PUBLISHED.iterdir()) == [
        "gridded-field-1.schema.json",
        "imagery-product-1.schema.json",
        "point-observation-1.schema.json",
        "radar-sweep-1.schema.json",
    ]
    assert oc.check(PUBLISHED) == []
    for contract in oc.CONTRACTS:
        schema = _schema(contract)
        assert schema["$id"] == f"urn:synapsecommand:observation:{contract.replace('/', ':')}"
        assert schema["x-observation-contract"] == contract
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_check_command_reads_current_and_a_stale_or_stray_file_is_named(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "synapse_cdm.observation_contracts",
            "--check",
            "--out",
            str(PUBLISHED),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"CURRENT: {PUBLISHED} vs gridded-field/1, point-observation/1, "
        "radar-sweep/1, imagery-product/1\n"
    )
    out = tmp_path / "observation"
    oc.write(out)
    assert oc.check(out) == []
    (out / "radar-sweep-1.schema.json").write_text("{}\n")
    (out / "extra-1.schema.json").write_text("{}\n")
    assert oc.check(out) == [
        f"{out / 'radar-sweep-1.schema.json'}: stale — the contract models changed; re-export",
        f"{out / 'extra-1.schema.json'}: not a contract this module publishes",
    ]


# -- the injected time convention ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, rendered",
    [
        ("2026-09-11T10:00:00Z", "2026-09-11T10:00:00.000Z"),
        ("2026-09-11T10:00:00.5Z", "2026-09-11T10:00:00.500Z"),
        ("2026-09-11T06:00:00-04:00", "2026-09-11T10:00:00.000Z"),
        ("2026-09-11T12:30:00.123456+02:00", "2026-09-11T10:30:00.123Z"),
    ],
)
def test_an_instant_with_its_zone_is_read_in_utc(text, rendered):
    assert oc.InjectedTime(text, "the caller states the slot").rendered == rendered


@pytest.mark.parametrize(
    "text",
    [
        "2026-09-11T10:00:00",
        "2026-09-11",
        "2026-09-11T10:00Z",
        "2026-09-11 10:00:00Z",
        "2026-09-11T10:00:00.1234567Z",
        " 2026-09-11T10:00:00Z",
    ],
    ids=["naive", "date", "no-seconds", "space", "seven-digits", "leading-space"],
)
def test_an_instant_without_its_zone_or_its_seconds_is_refused(text):
    with pytest.raises(ValueError) as caught:
        oc.parse_instant(text)
    assert str(caught.value) == (
        "an instant is RFC 3339 with seconds, at most six fractional digits and an explicit Z or "
        "numeric offset; a stamp without a zone is refused, never read as UTC"
    )


#: The four instants of checkpoint finding H-02 (2026-10-15): each passes the grammar and names a
#: real local time, and read in UTC each falls a day or a minute outside 0001 to 9999.
INSTANTS_PAST_UTC = [
    "0001-01-01T00:00:00+14:00",
    "0001-01-01T00:00:00+00:01",
    "9999-12-31T23:59:59-14:00",
    "9999-12-31T23:59:59.999999-00:01",
]
NOT_IN_UTC = (
    "the instant cannot be stated in UTC: read in UTC it falls before 0001-01-01 or after "
    "9999-12-31, which no timestamp holds"
)


@pytest.mark.parametrize("text", INSTANTS_PAST_UTC)
def test_an_instant_utc_cannot_state_is_the_fixed_value_error(text):
    with pytest.raises(ValueError) as caught:
        oc.parse_instant(text)
    assert (type(caught.value), str(caught.value)) == (ValueError, NOT_IN_UTC)
    with pytest.raises(ValueError) as caught:
        oc.InjectedTime(text, "the caller states the slot")
    assert (type(caught.value), str(caught.value)) == (ValueError, NOT_IN_UTC)


@pytest.mark.parametrize(
    "value", DATETIMES_PAST_UTC, ids=["first-day-plus-14", "last-day-minus-14"]
)
def test_an_aware_datetime_utc_cannot_state_is_the_same_value_error(value):
    with pytest.raises(ValueError) as caught:
        oc.InjectedTime(value, "the caller states the slot")
    assert (type(caught.value), str(caught.value)) == (ValueError, NOT_IN_UTC)


#: (value, whether an adapter reads it as a number). The largest double is (2 - 2**-52) * 2**1023,
#: which is 2**1024 - 2**971, so that integer is the last one read and the next is not.
JSON_NUMBERS = [
    (0, True),
    (-7, True),
    (1.5, True),
    (-0.0, True),
    (2**1024 - 2**971, True),
    (-(2**1024 - 2**971), True),
    (2**1024 - 2**971 + 1, False),
    (-(2**1024 - 2**971) - 1, False),
    (10**400, False),
    (float("nan"), False),
    (float("inf"), False),
    (float("-inf"), False),
    (True, False),
    (False, False),
    (None, False),
    ("1", False),
    ([1], False),
]


@pytest.mark.parametrize(
    ("value", "expected"),
    JSON_NUMBERS,
    ids=[
        "zero",
        "negative-int",
        "float",
        "negative-zero",
        "largest-double-integer",
        "its-negative",
        "one-past-it",
        "one-past-its-negative",
        "ten-to-the-400",
        "nan",
        "infinity",
        "negative-infinity",
        "true",
        "false",
        "none",
        "numeric-text",
        "list",
    ],
)
def test_a_json_number_is_finite_not_a_boolean_and_one_a_double_holds(value, expected):
    assert oc.json_number(value) is expected


def test_the_largest_integer_read_is_the_largest_double():
    assert oc.LARGEST_JSON_INTEGER == 2**1024 - 2**971
    assert float(oc.LARGEST_JSON_INTEGER) == sys.float_info.max


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", True),
        ("EX001", True),
        ("café", True),
        ("\U0001f30a", True),
        ("\ud83c\udf0a", False),
        ("\ud800", False),
        ("a\udfffb", False),
    ],
    ids=["empty", "ascii", "latin", "astral", "surrogate-pair", "lone-high", "lone-low"],
)
def test_utf8_text_refuses_a_lone_surrogate_and_nothing_else(text, expected):
    # A pair of surrogates written as two code points is two lone surrogates to Python: JSON's
    # `\\ud83c\\udf0a` escape decodes to the one astral character, never to this.
    assert oc.utf8_text(text) is expected


def test_the_instants_just_inside_the_edge_are_still_read():
    assert oc.parse_instant("0001-01-01T00:00:00+00:00") == dt.datetime(
        1, 1, 1, tzinfo=dt.timezone.utc
    )
    assert oc.parse_instant("0001-01-01T00:01:00+00:01") == dt.datetime(
        1, 1, 1, tzinfo=dt.timezone.utc
    )
    assert oc.InjectedTime("9999-12-31T09:59:59-14:00", "the caller states the slot").rendered == (
        "9999-12-31T23:59:59.000Z"
    )


def test_an_instant_that_does_not_exist_is_refused_and_so_is_a_naive_datetime_or_a_thin_basis():
    with pytest.raises(ValueError, match="^the instant names a date or time that does not exist$"):
        oc.parse_instant("2026-02-30T00:00:00Z")
    with pytest.raises(ValueError, match="an RFC 3339 text or an aware datetime"):
        oc.InjectedTime(dt.datetime(2026, 9, 11, 10), "the caller states the slot")
    with pytest.raises(ValueError, match="says, in words, where the instant came from"):
        oc.InjectedTime("2026-09-11T10:00:00Z", "slot")
    with pytest.raises(ValueError, match="longer than 1024 characters"):
        oc.InjectedTime("2026-09-11T10:00:00Z", "b" * 1025)
    frozen = oc.InjectedTime("2026-09-11T10:00:00Z", "the caller states the slot")
    with pytest.raises(AttributeError):
        frozen.basis = "another basis entirely"


# -- the station table and the site Entity -------------------------------------------------------

TABLE = {
    "name": "synthetic table A",
    "basis": "written for this test",
    "rows": [
        {"station_id": "EX001", "lat": 57.25, "lon": 21.5},
        {"station_id": "EX002", "lat": 56.75, "lon": 23.0},
    ],
}
SOURCE = SourceRef(system="SYNTH", adapter="synth", adapter_version="1.0.0", synthetic=True)
T_OBS = dt.datetime(2026, 9, 11, 10, 0, tzinfo=dt.timezone.utc)


def test_a_station_table_looks_up_a_row_and_refuses_a_station_twice_or_a_latitude_off_the_earth():
    table = oc.StationTable.model_validate(TABLE)
    assert table.position_of("EX002") == (56.75, 23.0)
    assert table.position_of("EX003") is None
    twice = with_(TABLE, rows=TABLE["rows"] + [TABLE["rows"][0]])
    assert _errors(oc.StationTable, twice) == [
        (("rows",), "value_error", "Value error, a station appears twice in the table")
    ]
    off = with_(TABLE, rows=[{"station_id": "EX001", "lat": 91.0, "lon": 21.5}])
    assert _errors(oc.StationTable, off) == [
        (("rows", 0, "lat"), "less_than_equal", "Input should be less than or equal to 90")
    ]


@pytest.mark.parametrize(
    "kwargs, position, basis",
    [
        (
            {"stated_position": (57.5, 22.25), "stated_position_basis": "the record's own fields"},
            (57.5, 22.25),
            "the record's own fields",
        ),
        (
            {"station_table": oc.StationTable.model_validate(TABLE)},
            (57.25, 21.5),
            "station table synthetic table A: written for this test",
        ),
        (
            {},
            None,
            "no position: the payload states none and no station table was supplied",
        ),
        (
            {"station_table": oc.StationTable.model_validate(with_(TABLE, rows=TABLE["rows"][1:]))},
            None,
            "no position: the payload states none and the station table has no row for this "
            "station",
        ),
    ],
    ids=["payload", "table", "no-table", "no-row"],
)
def test_the_site_position_comes_from_the_payload_then_the_table_then_nowhere(
    kwargs, position, basis
):
    status = OperationalStatus(state="p", namespace="synthetic status vocabulary")
    entity = oc.site_entity(
        source=SOURCE,
        system="SYNTH",
        station_id="EX001",
        site_class="buoy",
        valid_from=T_OBS,
        status=status,
        **kwargs,
    )
    assert entity.entity_id == uuid.uuid5(ID_NAMESPACE, "entity|SYNTH|EX001")
    assert entity.entity_type.value == "SENSOR"
    assert entity.affiliation.value == "UNKNOWN"
    assert [(s.system, s.external_id) for s in entity.source_ids] == [("SYNTH", "EX001")]
    assert entity.valid_from == T_OBS and entity.status == status
    assert entity.attributes == {"site_class": "buoy", "position_basis": basis}
    if position is None:
        assert entity.position is None
    else:
        assert (entity.position.lat, entity.position.lon) == position
        assert entity.position.position_source.value == "MANUAL"
        assert entity.position.alt_m is None


def test_every_site_class_is_a_sensor_until_ruled_and_an_unlisted_class_is_refused():
    assert {k: v.value for k, v in oc.SITE_ENTITY_TYPES.items()} == {
        "weather_station": "SENSOR",
        "buoy": "SENSOR",
        "tide_gauge": "SENSOR",
        "air_quality_site": "SENSOR",
        "radar_site": "SENSOR",
    }
    with pytest.raises(TypeError):
        oc.SITE_ENTITY_TYPES["buoy"] = None
    with pytest.raises(ValueError, match="^the site class is not in SITE_ENTITY_TYPES"):
        oc.site_entity(
            source=SOURCE,
            system="SYNTH",
            station_id="EX001",
            site_class="lighthouse",
            valid_from=T_OBS,
        )
    with pytest.raises(ValueError, match="^a position read from the payload states where"):
        oc.site_entity(
            source=SOURCE,
            system="SYNTH",
            station_id="EX001",
            site_class="buoy",
            valid_from=T_OBS,
            stated_position=(57.0, 21.0),
        )


# -- the observation Event -----------------------------------------------------------------------

T_START = dt.datetime(2026, 9, 11, 9, 0, tzinfo=dt.timezone.utc)
T_RECEIVED = dt.datetime(2026, 9, 11, 10, 5, tzinfo=dt.timezone.utc)
STATION = uuid.uuid5(ID_NAMESPACE, "entity|SYNTH|EX001")
IDS = [SourceId(system="SYNTH", external_id="EX001#0")]


def _hour(end=T_OBS):
    return TemporalValidity(effective={"start": T_START, "end": end})


def test_an_observation_event_carries_its_contract_and_the_end_of_its_interval():
    contract = oc.PointObservation.model_validate(POINT)
    event = oc.observation_event(
        source=SOURCE,
        source_ids=IDS,
        observation=contract,
        observed_at=T_OBS,
        received_at=T_RECEIVED,
        validity=_hour(),
        related_entities=[STATION],
    )
    dumped = event.model_dump(mode="json")
    assert dumped["event_type"] == "ENVIRONMENTAL_OBSERVATION"
    assert dumped["severity"] == "INFO"
    assert dumped["event_id"] == str(uuid.uuid5(ID_NAMESPACE, "event|SYNTH|EX001#0"))
    assert dumped["observed_at"] == "2026-09-11T10:00:00.000Z"
    assert dumped["received_at"] == "2026-09-11T10:05:00.000Z"
    assert dumped["validity"]["effective"] == {
        "start": "2026-09-11T09:00:00.000Z",
        "end": "2026-09-11T10:00:00.000Z",
    }
    assert dumped["related_entities"] == [str(STATION)]
    assert list(dumped["payload"]) == ["observation"]
    observation = dumped["payload"]["observation"]
    assert observation["contract"] == "point-observation/1"
    assert observation["readings"][1]["absence"] == {
        "cause": "sentinel",
        "mechanism": "the format's missing-value marker",
        "sentinel": "MM",
    }
    assert oc.contract_of(Event.model_validate_json(json.dumps(dumped))) == contract


def test_a_model_product_is_stamped_with_its_reference_time_never_its_valid_time():
    contract = oc.GriddedField.model_validate(GRIDDED)
    reference = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc)
    valid = TemporalValidity(
        effective={"start": "2026-09-11T12:00:00.000Z", "end": "2026-09-11T13:00:00.000Z"}
    )
    event = oc.observation_event(
        source=SOURCE,
        source_ids=[SourceId(system="SYNTH", external_id="msg-3")],
        observation=contract,
        observed_at=reference,
        received_at=dt.datetime(2026, 9, 11, 14, tzinfo=dt.timezone.utc),
        validity=valid,
    )
    assert event.model_dump(mode="json")["observed_at"] == "2026-09-11T12:00:00.000Z"
    assert event.related_entities == []


@pytest.mark.parametrize(
    "contract, kwargs, error, message",
    [
        (
            "point-observation/1",
            {"validity": None},
            ValueError,
            "an observation states its sensing interval as validity.effective with an end",
        ),
        (
            "point-observation/1",
            {"validity": TemporalValidity(effective={"start": T_START})},
            ValueError,
            "an observation states its sensing interval as validity.effective with an end",
        ),
        (
            "point-observation/1",
            {"observed_at": T_START},
            ValueError,
            "an observation's observed_at is the end of its sensing interval",
        ),
        (
            "point-observation/1",
            {"related_entities": []},
            ValueError,
            "a station or radar observation names its site in related_entities",
        ),
        (
            "point-observation/1",
            {"source_ids": []},
            ValueError,
            "an observation event states the source identifier it is keyed on",
        ),
        ("gridded-field/1", {}, ValueError, "a model product's observed_at is its reference_time"),
        (
            "gridded-field/1",
            {"observation": with_(GRIDDED, time={"source_time_system": UTC_SOURCE})},
            ValueError,
            "a model product states its reference_time",
        ),
        (
            "imagery-product/1",
            {"observation": with_(IMAGERY, product_class="reference")},
            ValueError,
            "a reference product states no sensing instant, so it is not an observation event",
        ),
        (
            "point-observation/1",
            {"observation": POINT},
            TypeError,
            "observation is one of the four contract models",
        ),
    ],
    ids=[
        "no-validity",
        "open-ended",
        "start-not-end",
        "no-site",
        "no-source-id",
        "valid-time-stamped",
        "no-reference-time",
        "reference-product",
        "a-dict",
    ],
)
def test_the_observed_at_rule_is_checked_not_trusted(contract, kwargs, error, message):
    arguments = {
        "source": SOURCE,
        "source_ids": IDS,
        "observation": oc.MODELS[contract].model_validate(LITERALS[contract]),
        "observed_at": T_OBS,
        "received_at": T_RECEIVED,
        "validity": _hour(),
        "related_entities": [STATION],
    }
    arguments.update(kwargs)
    if isinstance(arguments["observation"], dict) and error is not TypeError:
        arguments["observation"] = oc.parse_observation(arguments["observation"])
    with pytest.raises(error) as caught:
        oc.observation_event(**arguments)
    assert str(caught.value) == message


def test_contract_of_reads_only_an_environmental_observation_with_its_member():
    base = {
        "source": SOURCE.model_dump(mode="json"),
        "source_ids": [{"system": "SYNTH", "external_id": "EX001#0"}],
        "event_id": str(uuid.uuid5(ID_NAMESPACE, "event|SYNTH|EX001#0")),
        "severity": "INFO",
        "observed_at": "2026-09-11T10:00:00.000Z",
        "received_at": "2026-09-11T10:05:00.000Z",
    }
    other = Event.model_validate(
        {**base, "event_type": "DETECTION", "payload": {"observation": POINT}}
    )
    with pytest.raises(ValueError, match="^the event is not an ENVIRONMENTAL_OBSERVATION$"):
        oc.contract_of(other)
    empty = Event.model_validate({**base, "event_type": EventType.ENVIRONMENTAL_OBSERVATION})
    with pytest.raises(ValueError, match="^the event's payload has no observation member$"):
        oc.contract_of(empty)


# -- the MAPPINGS ledger -------------------------------------------------------------------------


def test_a_ledger_row_names_a_contract_field_or_is_refused():
    mapping = oc.contract_mapping(
        "point-observation/1", "readings[*].measurement.value", rule="number"
    )
    assert (mapping.to, mapping.rule, mapping.kind) == (
        "event:payload.observation.readings[*].measurement.value",
        "number",
        "field",
    )
    assert oc.contract_mapping("gridded-field/1", "grid.parameters.La1").to == (
        "event:payload.observation.grid.parameters.La1"
    )
    assert oc.contract_mapping("gridded-field/1", "values.locator.message", target="#[*]").to == (
        "#[*]:payload.observation.values.locator.message"
    )
    for contract, path in [
        ("point-observation/1", "readings[*].measurment.value"),
        ("point-observation/1", "station_id.code"),
        ("radar-sweep/1", "moments.name"),
        ("gridded-field/1", ""),
    ]:
        with pytest.raises(ValueError, match="^the field path names no field of the contract$"):
            oc.contract_mapping(contract, path)
    with pytest.raises(ValueError, match="^the contract is not one of the four$"):
        oc.contract_mapping("point-observation/2", "station_id")


def test_by_reference_arrays_are_a_declared_limitation_and_lost_without_it():
    """The ledger path the harness takes for an adapter with `MAPPINGS`: the mapped leaves are
    MAPPED, the arrays the contract carries by reference are DECLARED_LIMITATION with the
    structured limitation, and LOST without it."""
    twin = {"station": "EX001", "rows": [{"WSPD": 6.2}], "gates": [[1, 2], [3, 4]]}
    contract = oc.PointObservation.model_validate(with_(POINT, readings=POINT["readings"][:1]))
    event = oc.observation_event(
        source=SOURCE,
        source_ids=IDS,
        observation=contract,
        observed_at=T_OBS,
        received_at=T_RECEIVED,
        validity=_hour(),
        related_entities=[STATION],
    )
    mappings = oc.ledger_rows(
        "point-observation/1",
        {
            "station": "station_id",
            "rows[*].WSPD": ("readings[*].measurement.value", "number"),
        },
    )
    assert sorted(mappings) == ["rows[*].WSPD", "station"]
    limitation = oc.by_reference_limitation(["gates"])
    assert (limitation.id, limitation.unsupported_paths) == ("values-by-reference", ["gates"])
    dumped = [event.model_dump(mode="json")]
    declared = lossless.ledger(twin, dumped, mappings, unsupported=limitation.unsupported_paths)
    assert declared.counts == {"MAPPED": 2, "RESIDUAL": 0, "DECLARED_LIMITATION": 4, "LOST": 0}
    undeclared = lossless.ledger(twin, dumped, mappings)
    assert undeclared.counts == {"MAPPED": 2, "RESIDUAL": 0, "DECLARED_LIMITATION": 0, "LOST": 4}
    assert sorted(e.source_path for e in undeclared.lost) == [
        "gates[0][0]",
        "gates[0][1]",
        "gates[1][0]",
        "gates[1][1]",
    ]


def test_a_by_reference_limitation_names_at_least_one_path_and_no_prose():
    with pytest.raises(ValueError, match="^a by-reference limitation names at least one"):
        oc.by_reference_limitation([])
    with pytest.raises(ValidationError, match="which are prose and not paths"):
        oc.by_reference_limitation(["the gate values"])
    limitation = oc.by_reference_limitation(["b", "a", "b"], notes="two arrays")
    assert limitation.unsupported_paths == ["a", "b"]
    assert limitation.notes == "two arrays"
    assert limitation.summary == (
        "Array values are carried by reference — a locator, the shape and packing needed to open "
        "them, and a summary — and are not copied into the output."
    )


# -- the shared test support (tests/observation_support.py) --------------------------------------


@pytest.mark.parametrize(
    "station_id, form, expected",
    [
        ("EX001", "alphanumeric-5", []),
        ("EX099", "alphanumeric-5", []),
        ("EX000", "alphanumeric-5", ["'EX000' is not in the synthetic alphanumeric-5 block"]),
        ("EX100", "alphanumeric-5", ["'EX100' is not in the synthetic alphanumeric-5 block"]),
        ("AB123", "alphanumeric-5", ["'AB123' is not in the synthetic alphanumeric-5 block"]),
        ("0000001", "numeric-7", []),
        ("0000100", "numeric-7", ["'0000100' is not in the synthetic numeric-7 block"]),
        ("000000099", "air-quality-9", []),
        ("000000000042", "air-quality-12", []),
        ("1234", "numeric-4", ["'numeric-4' is not a station-id form of the convention"]),
    ],
)
def test_station_identifiers_are_held_to_their_synthetic_block(station_id, form, expected):
    assert support.station_id_problems(station_id, form) == expected


def test_radar_sites_aircraft_addresses_and_positions_are_held_to_the_convention():
    assert support.radar_site_problems("ZZZZ") == []
    assert support.radar_site_problems("XZZQ") == []
    assert support.radar_site_problems("XZZ1") == ["'XZZ1' is not ZZZZ or XZZA to XZZZ"]
    assert support.radar_site_problems("ABCD") == ["'ABCD' is not ZZZZ or XZZA to XZZZ"]
    assert support.aircraft_address_problems("0029c1") == []
    assert support.aircraft_address_problems("0030c1") == ["'0030c1' is not in the 0029xx block"]
    document = [
        {"position": {"lat": 57.0, "lon": 21.0}},
        {"position": {"lat": 59.0, "lon": 21.0}},
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[20.0, 56.0], [24.5, 56.0], [25.0, 58.5], [20.0, 56.0]]],
            }
        },
    ]
    assert support.positions_outside_the_rectangle(document) == [
        "$[1].position: (59.0, 21.0)",
        "$[2].geometry.coordinates[0][2]: (58.5, 25.0)",
    ]


def _record(name: str) -> dict:
    return {
        "file": name,
        "synthetic": True,
        "classification": "PUBLIC",
        "operational_data": False,
        "personal_data": False,
        "origin": "Synthetic payload written by this test from a literal.",
    }


def _fixture_tree(root: pathlib.Path, files: dict[str, bytes], listed: list[str]) -> pathlib.Path:
    directory = root / "fixtures" / "demo"
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    (directory / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "schema_id": PROVENANCE_SCHEMA_ID,
                "directory": "demo",
                "fixtures": [_record(n) for n in listed],
            }
        )
    )
    return directory


def test_the_fixture_set_checks_name_an_unlisted_payload_and_a_missing_twin(tmp_path):
    complete = _fixture_tree(
        tmp_path / "a",
        {"one.bin": b"\x01", "one.parsed.json": b"{}"},
        ["one.bin", "one.parsed.json"],
    )
    assert support.provenance_problems(complete) == []
    assert support.twin_problems(complete) == []
    broken = _fixture_tree(
        tmp_path / "b", {"one.bin": b"\x01", "two.parsed.json": b"{}"}, ["one.bin"]
    )
    assert support.provenance_problems(broken) == [
        "demo/two.parsed.json: on disk and not in PROVENANCE.json"
    ]
    assert support.twin_problems(broken) == [
        "one.bin: no one.parsed.json beside it",
        "two.parsed.json: a twin of no payload",
    ]


BUILDER = """\
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
OUTPUT = {"demo.parsed.json": b'{"value": 1}\\n'}
MARKER = "built from source"


def main(argv):
    if argv[1:] != ["--check"]:
        for name, data in OUTPUT.items():
            (HERE / name).write_bytes(data)
        return 0
    stale = [n for n, d in OUTPUT.items() if (HERE / n).read_bytes() != d]
    print("STALE: " + ", ".join(stale) if stale else "CURRENT")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
"""


def _builder_tree(root: pathlib.Path, source: str = BUILDER) -> pathlib.Path:
    directory = root / "synapse_cdm" / "fixtures" / "demo"
    (directory / "spec").mkdir(parents=True)
    (directory / "spec" / "build_fixtures.py").write_text(source)
    (directory / "demo.parsed.json").write_bytes(b'{"value": 1}\n')
    return directory


def test_a_builder_check_is_current_from_an_outside_directory_and_leaves_no_trace(tmp_path):
    directory = _builder_tree(tmp_path / "tree")
    outside = tmp_path / "outside"
    outside.mkdir()
    assert support.builder_problems(directory, outside) == []
    result = support.run_builder_check(directory, outside)
    assert (result.returncode, result.stdout, result.stderr) == (0, "CURRENT\n", "")


def test_a_stale_set_and_a_builder_that_writes_on_check_are_both_named(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    stale = _builder_tree(tmp_path / "stale")
    (stale / "demo.parsed.json").write_bytes(b'{"value": 2}\n')
    assert support.builder_problems(stale, outside) == [
        "--check exited 1: STALE: demo.parsed.json\n",
        "--check did not end with CURRENT: 'STALE: demo.parsed.json\\n'",
    ]
    writer = _builder_tree(
        tmp_path / "writer", BUILDER.replace('if argv[1:] != ["--check"]:', "if True:")
    )
    (writer / "demo.parsed.json").write_bytes(b"old\n")
    assert support.builder_problems(writer, outside) == [
        "--check did not end with CURRENT: ''",
        "--check changed the fixture directory: ['demo.parsed.json']",
    ]


def test_a_builder_that_writes_into_its_working_directory_is_named(tmp_path):
    """Checkpoint finding H-08 (2026-10-15): the template watched the fixture directory only, so
    a `--check` that left a file in the directory it was run from passed, with the file left
    behind. It reads CURRENT and leaves the fixture directory alone; only the stray is wrong."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.bin").write_bytes(b"there before")
    stray = _builder_tree(
        tmp_path / "stray",
        BUILDER.replace(
            "    stale = [",
            '    pathlib.Path("stray.bin").write_bytes(b"x")\n'
            '    pathlib.Path("kept.bin").write_bytes(b"changed")\n'
            "    stale = [",
        ),
    )
    assert support.builder_problems(stray, outside) == [
        "--check changed its working directory: ['kept.bin', 'stray.bin']",
    ]
    assert support.run_builder_check(stray, outside).stdout == "CURRENT\n"


def test_the_builder_is_loaded_from_its_source_with_no_bytecode_and_sys_path_restored(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    directory = _builder_tree(tmp_path / "tree")
    before = list(sys.path)
    module = support.load_builder(directory / "spec" / "build_fixtures.py")
    assert module.MARKER == "built from source"
    assert module.OUTPUT == {"demo.parsed.json": b'{"value": 1}\n'}
    assert sys.path == before
    assert not (directory / "spec" / "__pycache__").exists()
