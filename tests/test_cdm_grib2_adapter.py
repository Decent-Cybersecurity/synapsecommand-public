"""`grib2`, #29 in the ordinal table: one GRIB2 message -> one gridded-field Event per field.

Every expectation here is a literal written from the fixture builder's literals
(`fixtures/grib2/spec/build_fixtures.py`: GDAL's options and the grids it was given, or the
script's own encoder, neither sharing code with the adapter) and the GRIB2 tables, never read back
from the adapter: a value is the grid literal it was written from, a footprint vertex is PROJ's
reading of the same grid point (`gdaltransform`, an independent implementation), an identifier is
the uuid5 of the documented namespace and name built here, and every refusal is its code and its
whole text. The twins the builder writes are the decode's expectation: each is compared with what
the adapter decodes from its octets.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/grib2/` and runs the
packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import copy
import json
import math
import pathlib
import pickle
import struct
import tracemalloc
import uuid
import zlib

import pytest

import synapse_cdm
from synapse_cdm import lossless, manifest, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import grib2
from synapse_cdm.adapters.grib2 import Grib2Adapter, Grib2Refused
from synapse_cdm.manifest import LimitKind, UnknownFields
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "grib2"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
GDAL_ROWS = "GDAL 3.13.3 GDAL_DATA, generated from wmo-im/GRIB2 at a9c4acc"

CASES = sorted(p.stem for p in FIXTURES.glob("*.grb2"))
BUILDER = support.load_builder(FIXTURES / "spec" / "build_fixtures.py", "grib2_builder")


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _octets(name: str) -> bytes:
    return (FIXTURES / f"{name}.grb2").read_bytes()


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _translate(payload, clock=None, **kwargs) -> list[dict]:
    adapter = Grib2Adapter(clock=clock or times.frozen_clock(), **kwargs)
    return [o.model_dump(mode="json") for o in adapter.to_cdm(payload)]


def _refusal(payload) -> Grib2Refused:
    with pytest.raises(Grib2Refused) as raised:
        Grib2Adapter(clock=times.frozen_clock()).to_cdm(payload)
    return raised.value


def _observation(obj: dict) -> dict:
    return obj["payload"]["observation"]


def _flags(obj: dict) -> list[tuple]:
    return [
        (f["name"], f["value"], f["namespace"], f["applies_to"])
        for f in _observation(obj)["quality_flags"]
    ]


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["grib2"]
    assert cls is Grib2Adapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "grib2",
        "1.0.0",
        "ingest",
        "GRIB2",
    )
    assert grib2.__doc__.splitlines()[0] == (
        "`grib2`, #29 in the ordinal table: one GRIB2 message -> CDM, ingest only."
    )
    meta = cls.metadata
    assert (
        meta.format.name,
        meta.format.version,
        meta.binding.value,
        meta.license_class.value,
        meta.maturity.level.value,
        meta.claim_status.value,
        meta.residual.value,
    ) == (
        "GRIB2 (WMO FM 92 GRIB edition 2)",
        "GRIB edition 2, read against NCEP's WMO GRIB2 Documentation version 37.0.0 (2026-06-01)",
        "standard-encoding",
        "PUBLIC_GOVERNMENT",
        "L3",
        "VERIFIED",
        "structured",
    )
    limits = meta.capabilities.limits
    # U-07: one message <= 8 MiB; MRMS's 49,003,500 octets of PNG rows under 64 MiB; eight times
    # RAP's two fields; the twin's five levels under the dis7 envelope's 16.
    assert (
        limits.max_input_bytes,
        limits.max_depth,
        limits.max_objects,
        limits.max_decompressed_bytes,
        limits.max_parse_seconds,
    ) == (8388608, 16, 16, 67108864, None)
    assert sorted(limits.absent_because) == ["max_parse_seconds"]
    assert sorted(limits.declared_because) == [
        "max_decompressed_bytes",
        "max_depth",
        "max_input_bytes",
        "max_objects",
    ]
    for basis in [*limits.declared_because.values(), grib2.MAX_GRID_POINTS_BASIS]:
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
        )
    # The brief's wording for the input bound (tests/test_cdm_input_bounds.py's rule).
    assert limits.declared_because["max_input_bytes"].source.startswith(
        "largest message of 2026-09-11 12Z across HRRR sfc/prs/nat/subh and RAP awp130pgrb is "
        "3,810,470 B (wire-facts F02); NOT the format's normative maximum."
    )
    assert "49,003,500" in limits.declared_because["max_decompressed_bytes"].source
    assert (grib2.MAX_GRID_POINTS, grib2.MAX_FIELDS) == (33554432, 16)
    assert "24,500,000 points" in grib2.MAX_GRID_POINTS_BASIS.source
    # Each basis names a test of this module that exists.
    names = set(globals())
    for basis in [*limits.declared_because.values(), grib2.MAX_GRID_POINTS_BASIS]:
        module, _, test = basis.test.partition("::")
        if module == "tests/test_cdm_grib2_adapter.py":
            assert test in names, test
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "values-by-reference",
        "jpeg2000-values-unsupported",
        "message-octets-by-reference",
        "one-message-per-call",
        "templates-read",
        "tables-read-by-row",
        "first-fixed-surface",
        "footprint-outline",
        "evidence-availability",
    ]
    assert manifest.unsupported_paths(meta.limitations) == ("arrays", "codestreams", "wire_hex")


def test_the_ledger_binds_each_field_to_its_own_event_and_the_message_to_every_one():
    assert {key: [m.to for m in (v if isinstance(v, tuple) else (v,))] for key, v in
            Grib2Adapter.MAPPINGS.items()} == {
        "indicator": ["event:residual.data.indicator"],
        "identification": ["event:residual.data.identification"],
        "local_use": ["event:residual.data.local_use"],
        "fields[*].grid.parameters": [
            "#[*]:residual.data.field.grid.parameters",
            "#[*]:payload.observation.grid.parameters",
        ],
        "fields[*]": ["#[*]:residual.data.field"],
        "summaries[*].count": ["#[*]:payload.observation.values.summary.count"],
        "summaries[*].missing_count": ["#[*]:payload.observation.values.summary.missing_count"],
        "summaries[*].min": ["#[*]:payload.observation.values.summary.min"],
        "summaries[*].max": ["#[*]:payload.observation.values.summary.max"],
        "summaries[*]": ["#[*]:payload.observation.values.summary"],
    }  # fmt: skip
    assert sorted(Grib2Adapter.TRANSFORMS) == ["arrays", "codestreams", "wire_hex"]


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_mapped_parked_or_a_declared_limitation(name):
    twin = _twin(name)
    objects = _translate(twin)
    book = lossless.ledger(
        twin,
        objects,
        Grib2Adapter.MAPPINGS,
        unsupported=manifest.unsupported_paths(Grib2Adapter.metadata.limitations),
    )
    assert book.lost == ()
    limited = {e.source_path for e in book.entries if e.category == "DECLARED_LIMITATION"}
    assert "wire_hex" in limited
    if name == "jpeg2000_reference_form":
        # 5.40's values are UNSUPPORTED, under their own limitation, and nothing summarises them.
        assert {e.expected["rule"] for e in book.entries if e.source_path == "codestreams[0]"} == {
            "limitation:codestreams"
        }
        assert twin["summaries"] == [None] and twin["arrays"][0]["packed_hex"] is None


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert len(CASES) == 13
    assert len(list(MALFORMED.glob("*.grb2"))) == 11


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_stated_position_lies_in_the_baltic_rectangle(name):
    golden = json.loads((GOLDEN / f"{name}.cdm.json").read_text(encoding="utf-8"))
    assert support.positions_outside_the_rectangle(golden) == []
    south, north, west, east = support.BALTIC_RECTANGLE
    for field in _twin(name)["fields"]:
        p = field["grid"]["parameters"]
        assert south * 1e6 <= p["la1"] <= north * 1e6
        assert west * 1e6 <= p["lo1"] <= east * 1e6


@pytest.mark.parametrize("name", CASES)
def test_the_decode_of_each_message_is_the_twin_its_builder_wrote(name):
    assert grib2.twin_of(_octets(name)) == _twin(name)


@pytest.mark.parametrize("name", CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    assert _translate(_octets(name)) == _translate(_twin(name))


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    a = json.loads((GOLDEN / f"{name}.cdm.json").read_text(encoding="utf-8"))
    b = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text(encoding="utf-8"))
    assert a == b == _translate(_octets(name))


# ================================================================== every value, by hand

W3X2 = [4.0, 5.5, 6.75, 1.5, 2.25, 3.125]  # the ASCII grid's rows, south first (scanning 0x40)
#: 10 + 0.5 i + 0.25 j + ((7 i + 3 j) mod 5) x 0.125 for column i and ASCII row j (north first),
#: worked out by hand and stored south first: the first line is ASCII row 7, the last row 0.
G8 = [
    11.875, 12.625, 12.75, 13.5, 14.25, 14.375, 15.125, 15.25,
    11.875, 12.0, 12.75, 13.5, 13.625, 14.375, 14.5, 15.25,
    11.25, 12.0, 12.75, 12.875, 13.625, 13.75, 14.5, 15.25,
    11.25, 12.0, 12.125, 12.875, 13.0, 13.75, 14.5, 14.625,
    11.25, 11.375, 12.125, 12.25, 13.0, 13.75, 13.875, 14.625,
    10.625, 11.375, 11.5, 12.25, 13.0, 13.125, 13.875, 14.0,
    10.625, 10.75, 11.5, 12.25, 12.375, 13.125, 13.25, 14.0,
    10.0, 10.75, 11.5, 11.625, 12.375, 12.5, 13.25, 14.0,
]  # fmt: skip
#: The same grid with a nodata cell wherever the ASCII row index j (north first, 0..7) and the
#: column i add up to a multiple of 7: stored row k is ASCII row 7 - k.
G8_MISSING = [None if (i + (7 - k)) % 7 == 0 else G8[8 * k + i] for k in range(8) for i in range(8)]

VALUES = {
    "simple_packing_latlon": [W3X2],
    "png_16_bit": [W3X2],
    "lambert_conformal_simple": [W3X2],
    "png_8_bit": [[1250.0, 1255.0, 1003.0, 1000.0, 1100.0, 1200.0]],
    "complex_order_1": [G8],
    "complex_order_2_missing": [G8_MISSING],
    "bitmap_simple_packing": [
        [1500.0, 2400.0, None, 9000.0, None, 4000.0, 4100.0, 4200.0, 7000.0, None, 300.0, 15000.0]
    ],
    "two_fields_one_message": [
        [-4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0],
        [12.5, 12.0, 11.5, 11.0, 10.5, 10.0, 9.5, 9.0, 8.5],
    ],
    "zero_width_accumulation": [[0.0] * 6],
    "complex_order_2_with_bitmap": [
        [
            61.5, 62.0, 62.5, None, 64.0,
            60.0, None, 61.0, 61.5, 63.5,
            58.5, 59.0, 59.0, 59.5, None,
            None, 57.0, 56.5, 56.0, 55.5,
        ]
    ],
    "complex_order_1_primary_and_secondary_missing": [
        [3.5, 4.0, None, 4.5, None, None, None, None, 5.0, None, 5.5, 6.0, None, None, None, None]
    ],
    "mrms_style_png_sentinels": [
        [
            0.0, 2.5, 12.7, -1.0,
            0.5, 0.5, 3.0, 4.5,
            -3.0, -3.0, 1.0, 0.0,
            7.5, 25.0, 6.2, -1.0,
            0.0, 0.1, 0.2, 0.4,
        ]
    ],
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(VALUES))
def test_every_value_of_every_field_is_its_grid_literal(name):
    octets = _octets(name)
    decoded = [grib2.field_values(octets, i) for i in range(len(VALUES[name]))]
    # Exact equality: every literal is a multiple of the packing's step, so it decodes exactly.
    assert decoded == VALUES[name]
    assert all(type(v) is float for field in decoded for v in field if v is not None)


def test_a_jpeg2000_field_is_not_decoded():
    with pytest.raises(ValueError) as raised:
        grib2.field_values(_octets("jpeg2000_reference_form"), 0)
    assert str(raised.value) == "a Template 5.40 field's values are not decoded"


#: (count, missing_count, min, max) per field, worked from the literals above: the bitmap's absent
#: points, the management's missing values and the sentinels all count as missing, and the
#: extremes are of the rest.
SUMMARIES = {
    "simple_packing_latlon": [(6, 0, 1.5, 6.75)],
    "png_16_bit": [(6, 0, 1.5, 6.75)],
    "lambert_conformal_simple": [(6, 0, 1.5, 6.75)],
    "png_8_bit": [(6, 0, 1000.0, 1255.0)],
    "complex_order_1": [(64, 0, 10.0, 15.25)],
    "complex_order_2_missing": [(64, 10, 10.625, 15.25)],
    "bitmap_simple_packing": [(12, 3, 300.0, 15000.0)],
    "two_fields_one_message": [(9, 0, -4.0, 0.0), (9, 0, 8.5, 12.5)],
    "zero_width_accumulation": [(6, 0, 0.0, 0.0)],
    "complex_order_2_with_bitmap": [(20, 4, 55.5, 64.0)],
    "complex_order_1_primary_and_secondary_missing": [(16, 10, 3.5, 6.0)],
    "mrms_style_png_sentinels": [(20, 4, 0.0, 25.0)],
    "jpeg2000_reference_form": [None],
}


@pytest.mark.parametrize("name", CASES)
def test_each_summary_counts_every_missing_mechanism_and_states_the_extremes_of_the_rest(name):
    events = _translate(_octets(name))
    got = []
    for event in events:
        summary = _observation(event)["values"]["summary"]
        got.append(
            None
            if summary is None
            else (summary["count"], summary["missing_count"], summary["min"], summary["max"])
        )
    assert got == SUMMARIES[name]


# ================================================================== one Event, written out


def test_the_simple_packing_message_becomes_one_event_as_written_by_hand():
    [event] = _translate(_octets("simple_packing_latlon"))
    twin = _twin("simple_packing_latlon")
    external = (
        "centre 7.0/2026-04-29T06:00:00.000Z/parameter 0.2.2/process 2.255.0/"
        "level 103:0:10,255:0:0/time 1:1/grid 3.0 3x2 at 57125000,21125000"
    )
    locator = {
        "kind": "grib",
        "message": 0,
        "field": 0,
        "byte_offset": 0,
        "frame_sha256": None,
        "granule_id": None,
    }
    grid_parameters = {
        "earth_shape": 5,
        "radius_scale_factor": 255,
        "radius_scaled_value": 4294967295,
        "major_axis_scale_factor": 255,
        "major_axis_scaled_value": 4294967295,
        "minor_axis_scale_factor": 255,
        "minor_axis_scaled_value": 4294967295,
        "ni": 3,
        "nj": 2,
        "basic_angle": 0,
        "basic_angle_subdivisions": 4294967295,
        "la1": 57125000,
        "lo1": 21125000,
        "resolution_flags": 48,
        "la2": 57375000,
        "lo2": 21625000,
        "di": 250000,
        "dj": 250000,
        "scanning_mode": 64,
    }
    assert {k: event[k] for k in ("object_kind", "schema_version", "event_type", "severity")} == {
        "object_kind": "event",
        "schema_version": "3.2.0",
        "event_type": "ENVIRONMENTAL_OBSERVATION",
        "severity": "INFO",
    }
    assert event["source_ids"] == [{"system": "GRIB2", "external_id": external}]
    assert event["event_id"] == _uuid("event", "GRIB2", external)
    assert event["source"] == {
        "system": "GRIB2",
        "adapter": "grib2",
        "adapter_version": "1.0.0",
        "synthetic": True,
        "format_name": "GRIB2 (WMO FM 92 GRIB edition 2)",
        "format_version": (
            "GRIB edition 2, read against NCEP's WMO GRIB2 Documentation version 37.0.0 "
            "(2026-06-01)"
        ),
        "original_id": None,
        "record_index": 0,
        "observed_at": "2026-04-29T06:00:00.000Z",
        "source_hash": None,
        "transformations": [
            grib2.T_REFERENCE,
            grib2.T_VALID,
            grib2.T_LEVEL,
            grib2.T_FOOTPRINT_LATLON,
            grib2.T_SUMMARY,
        ],
    }
    assert (event["observed_at"], event["received_at"]) == ("2026-04-29T06:00:00.000Z", FROZEN)
    # A one-hour forecast: valid at 07:00, observed_at the 06:00 reference, never the future.
    assert event["validity"] == {
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
        "effective": {"start": "2026-04-29T07:00:00.000Z", "end": "2026-04-29T07:00:00.000Z"},
    }
    assert event["geometry"] == {
        "type": "Polygon",
        "coordinates": [
            [
                [21.125, 57.125],
                [21.625, 57.125],
                [21.625, 57.375],
                [21.125, 57.375],
                [21.125, 57.125],
            ]
        ],
    }
    assert {k: event[k] for k in ("related_entities", "quality", "integrity", "oes", "status")} == {
        "related_entities": [],
        "quality": None,
        "integrity": None,
        "oes": None,
        "status": None,
    }
    assert event["payload"] == {
        "observation": {
            "contract": "gridded-field/1",
            "product_class": "forecast",
            "product_version": {
                "run": None,
                "version": "GRIB2 master tables version 2, local tables version 0",
                "production_time_verbatim": None,
                "producer": "originating centre 7, subcentre 0, generating process 2.255.0",
            },
            "time": {
                "source_time_system": {
                    "name": "UTC",
                    "stated_by": "source",
                    "basis": (
                        "GRIB2 Section 1 octets 13-19, the reference time as year, month, day, "
                        "hour, minute and second; GRIB2 states its times in UTC"
                    ),
                },
                "reference_time": "2026-04-29T06:00:00.000Z",
                "reference_time_significance": {
                    "code": "1",
                    "namespace": "GRIB2 Code Table 1.2",
                    "meaning": "Start of Forecast",
                },
                "forecast_offset": {
                    "value": 1.0,
                    "unit": "Hour",
                    "unit_namespace": "GRIB2 Code Table 4.4",
                },
                "statistical_process": None,
            },
            "locator": locator,
            "quality_flags": [
                {
                    "name": "production_status",
                    "value": 0,
                    "namespace": "GRIB2 Code Table 1.3",
                    "applies_to": "message",
                },
                {
                    "name": "bitmap_indicator",
                    "value": 255,
                    "namespace": "GRIB2 Code Table 6.0",
                    "applies_to": "field",
                },
                {
                    "name": "points_without_value",
                    "value": 0,
                    "namespace": "GRIB2 Section 6 bitmap",
                    "applies_to": "field",
                },
            ],
            "quality_flags_basis": None,
            "quantity": {
                "name": "UGRD",
                "code": "0.2.2",
                "namespace": (
                    f"GRIB2 Code Table 4.2 (discipline.category.number), {GDAL_ROWS}: "
                    "grib2_table_4_2_0_2"
                ),
            },
            "unit": {"unit": "m/s", "unit_namespace": f"{GDAL_ROWS}: grib2_table_4_2_0_2"},
            "level": {
                "type": "Specified height level above ground",
                "code": "103",
                "value": 10.0,
                "unit": "m",
                "namespace": f"GRIB2 Code Table 4.5, {GDAL_ROWS}: grib2_table_4_5",
            },
            "datum": None,
            "grid": {
                "namespace": "GRIB2 Code Table 3.1",
                "template": "3.0",
                "shape": [2, 3],
                "scanning_mode": "01000000",
                "cell_size": [
                    {
                        "value": 250000.0,
                        "unit": "10^-6 degree",
                        "unit_namespace": "GRIB2 Template 3.0 Note 1 (units of 10^-6 degree)",
                    }
                ]
                * 2,
                "parameters": grid_parameters,
            },
            "values": {
                "mode": "reference",
                "locator": locator,
                "shape": [2, 3],
                "dtype": "16-bit unsigned integers",
                "encoding": (
                    "GRIB2 Code Table 5.0 template 0, Grid Point Data - Simple Packing: Y = (R + "
                    "X x 2^E) / 10^D with R = 1500.0, E = -3, D = 3"
                ),
                # Y = (1500 + X / 8) / 1000 = X x 0.000125 + 1.5.
                "scale": 0.000125,
                "offset": 1.5,
                "fill": None,
                "summary": {"count": 6, "missing_count": 0, "min": 1.5, "max": 6.75},
            },
        }
    }
    assert event["residual"] == {
        "namespace": "GRIB2 (WMO FM 92 GRIB edition 2)",
        "data": {
            "indicator": {"discipline": 0, "edition": 2, "total_length": 196},
            "identification": twin["identification"],
            "local_use": {"section_length": 5, "octets_hex": ""},
            "field": twin["fields"][0],
        },
    }
    assert twin["fields"][0]["grid"]["parameters"] == grid_parameters


# ================================================================== time, class, quantity, level

#: (class, significance, forecast offset, statistical process, effective start, effective end).
TIMES = {
    "simple_packing_latlon": ("forecast", ("1", "Start of Forecast"), (1.0, "Hour"), None,
                              "07:00", "07:00"),
    "two_fields_one_message": ("forecast", ("1", "Start of Forecast"), (2.0, "Hour"), None,
                               "08:00", "08:00"),
    "png_8_bit": ("analysis", ("1", "Start of Forecast"), (0.0, "Hour"), None, "06:00", "06:00"),
    "complex_order_1": ("analysis", ("1", "Start of Forecast"), (0.0, "Hour"), None,
                        "06:00", "06:00"),
    # Table 1.4 code 1 with a zero offset: an analysis by the validity; 4.8's interval is the hour.
    "zero_width_accumulation": ("forecast", ("1", "Start of Forecast"), (0.0, "Hour"),
                                ("1", "Accumulation"), "06:00", "07:00"),
    "mrms_style_png_sentinels": ("modelled_estimate", ("3", "Observation Time"), (0.0, "Minute"),
                                 None, "06:00", "06:00"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(TIMES))
def test_the_reference_time_the_validity_and_the_class_follow_the_message(name):
    product_class, significance, offset, process, start, end = TIMES[name]
    for event in _translate(_octets(name)):
        observation = _observation(event)
        time = observation["time"]
        assert observation["product_class"] == product_class
        assert event["observed_at"] == time["reference_time"] == "2026-04-29T06:00:00.000Z"
        sig = time["reference_time_significance"]
        assert (sig["code"], sig["meaning"], sig["namespace"]) == (
            *significance,
            "GRIB2 Code Table 1.2",
        )
        offset_stated = time["forecast_offset"]
        assert (offset_stated["value"], offset_stated["unit"]) == offset
        stated = time["statistical_process"]
        assert (None if stated is None else (stated["code"], stated["meaning"])) == process
        assert event["validity"]["effective"] == {
            "start": f"2026-04-29T{start}:00.000Z",
            "end": f"2026-04-29T{end}:00.000Z",
        }


#: (quantity name, code, unit, level as (type, code, value, unit)) per fixture's first field.
QUANTITIES = {
    "simple_packing_latlon": ("UGRD", "0.2.2", "m/s",
                              ("Specified height level above ground", "103", 10.0, "m")),
    "png_8_bit": ("VIS", "0.19.0", "m", ("Ground or water surface", "1", None, None)),
    "complex_order_1": ("RH", "0.1.1", "%",
                        ("Specified height level above ground", "103", 2.0, "m")),
    "two_fields_one_message": ("UGRD", "0.2.2", "m/s", ("Isobaric surface", "100", 10000.0, "Pa")),
    "zero_width_accumulation": ("APCP", "0.1.8", "kg/(m^2)",
                                ("Ground or water surface", "1", None, None)),
    "mrms_style_png_sentinels": ("MultiSensor_QPE_01H_Pass2", "209.6.37", "mm",
                                 ("Specific altitude above mean sea level", "102", 0.0, "m")),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(QUANTITIES))
def test_the_quantity_its_unit_and_its_level_are_stated_from_the_rows_read(name):
    short, code, unit, level = QUANTITIES[name]
    observation = _observation(_translate(_octets(name))[0])
    assert (observation["quantity"]["name"], observation["quantity"]["code"]) == (short, code)
    assert observation["unit"]["unit"] == unit
    stated = observation["level"]
    assert (stated["type"], stated["code"], stated["value"], stated["unit"]) == level
    if name == "mrms_style_png_sentinels":
        assert observation["unit"]["unit_namespace"] == (
            "NSSL Operational MRMS GRIB2 Tables, MRMS Version 12.2 (research-grib2 F04)"
        )


def test_a_parameter_and_a_surface_no_row_names_keep_their_codes_and_state_no_unit():
    # 0.3.4 (geopotential) and surface 104 (sigma) are rows this module does not list.
    octets = _simple_message(product=BUILDER.product0(3, 4, 2, 1, 1, 104, 4, 9950))
    observation = _observation(_translate(octets)[0])
    assert observation["quantity"] == {
        "name": None,
        "code": "0.3.4",
        "namespace": "GRIB2 Code Table 4.2 (discipline.category.number)",
    }
    assert observation["unit"] is None
    assert observation["level"] == {
        "type": None,
        "code": "104",
        "value": None,
        "unit": None,
        "namespace": "GRIB2 Code Table 4.5",
    }


#: The Table 4.2 rows of the HRRR and RAP fields the design record names (R5 review 1, F-02):
#: (discipline, category, number) -> (short name, unit, the file's name), each read from GDAL
#: 3.13.3's table file of that name (the pin lists the file, its SHA-256 and the row).
NAMED_ROWS = {
    (0, 0, 0): ("TMP", "K", "grib2_table_4_2_0_0"),
    (0, 3, 0): ("PRES", "Pa", "grib2_table_4_2_0_3"),
    (0, 3, 5): ("HGT", "gpm", "grib2_table_4_2_0_3"),
    (0, 1, 193): ("CFRZR", None, "grib2_table_4_2_local_NCEP"),
    (0, 3, 196): ("HPBL", "m", "grib2_table_4_2_local_NCEP"),
    (0, 16, 196): ("REFC", "dB", "grib2_table_4_2_local_NCEP"),
    (3, 192, 1): ("SBT123", "K", "grib2_table_4_2_local_NCEP"),
    (3, 192, 2): ("SBT124", "K", "grib2_table_4_2_local_NCEP"),
    (3, 192, 7): ("SBT113", "K", "grib2_table_4_2_local_NCEP"),
    (3, 192, 8): ("SBT114", "K", "grib2_table_4_2_local_NCEP"),
}


def _parameter_message(discipline: int, category: int, number: int, centre: int = 7) -> bytes:
    return BUILDER.message(
        discipline,
        [
            BUILDER.s1_octets(BUILDER.identification(centre=centre)),
            BUILDER.s3_octets(GRID),
            BUILDER.s4_octets(BUILDER.product0(category, number, 2, 1, 1, 1, 0, 0)),
            BUILDER.s5_octets(
                BUILDER.representation(0, 6, 21, **BUILDER.scaling(1500.0, -3, 3, 16))
            ),
            BUILDER.section(6, b"\xff"),
            BUILDER.section(7, BUILDER.pack_bits(CODES, 16)),
        ],
    )


@pytest.mark.parametrize("key", sorted(NAMED_ROWS), ids=lambda k: ".".join(map(str, k)))
def test_the_hrrr_and_rap_parameters_state_their_table_4_2_rows(key):
    short, unit, file = NAMED_ROWS[key]
    source = (
        f"{GDAL_ROWS}: {file}"
        if file != "grib2_table_4_2_local_NCEP"
        else f"GDAL 3.13.3 GDAL_DATA: {file}"
    )
    observation = _observation(_translate(_parameter_message(*key))[0])
    assert observation["quantity"] == {
        "name": short,
        "code": ".".join(map(str, key)),
        "namespace": f"GRIB2 Code Table 4.2 (discipline.category.number), {source}",
    }
    # CFRZR's unit column holds "0=no; 1=yes", the meanings of its codes: no unit is stated.
    assert observation["unit"] == (
        None if unit is None else {"unit": unit, "unit_namespace": source}
    )


def test_a_local_row_is_read_only_for_the_centre_that_wrote_it():
    # 0.16.196 is NCEP's REFC; from centre 161 the same code is a row this module does not list.
    observation = _observation(_translate(_parameter_message(0, 16, 196, centre=161))[0])
    assert observation["quantity"] == {
        "name": None,
        "code": "0.16.196",
        "namespace": "GRIB2 Code Table 4.2 (discipline.category.number)",
    }
    assert observation["unit"] is None


#: Every flag, verbatim: (name, value, namespace, applies_to), per Event.
FLAGS = {
    "bitmap_simple_packing": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 0, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 3, "GRIB2 Section 6 bitmap", "field"),
    ]],
    "complex_order_2_missing": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 255, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 0, "GRIB2 Section 6 bitmap", "field"),
        ("primary_missing_count", 10, "GRIB2 Code Table 5.5", "field"),
    ]],
    "complex_order_2_with_bitmap": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 0, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 4, "GRIB2 Section 6 bitmap", "field"),
    ]],
    "complex_order_1_primary_and_secondary_missing": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 255, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 0, "GRIB2 Section 6 bitmap", "field"),
        ("primary_missing_count", 5, "GRIB2 Code Table 5.5", "field"),
        ("secondary_missing_count", 5, "GRIB2 Code Table 5.5", "field"),
    ]],
    "zero_width_accumulation": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 255, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 0, "GRIB2 Section 6 bitmap", "field"),
        ("missing_in_statistical_process", 0,
         "GRIB2 Product Definition Template 4.8 octets 43-46", "field"),
    ]],
    "mrms_style_png_sentinels": [[
        ("production_status", 0, "GRIB2 Code Table 1.3", "message"),
        ("bitmap_indicator", 255, "GRIB2 Code Table 6.0", "field"),
        ("points_without_value", 0, "GRIB2 Section 6 bitmap", "field"),
        ("sentinel_missing_count", 2,
         "NSSL Operational MRMS GRIB2 Tables, MRMS Version 12.2 (research-grib2 F04): "
         "Missing = -1.0", "field"),
        ("sentinel_no_coverage_count", 2,
         "NSSL Operational MRMS GRIB2 Tables, MRMS Version 12.2 (research-grib2 F04): "
         "No Coverage = -3.0", "field"),
    ]],
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FLAGS))
def test_each_missing_mechanism_is_its_own_flag_and_never_merged(name):
    assert [_flags(event) for event in _translate(_octets(name))] == FLAGS[name]


def test_two_fields_in_one_message_are_two_events_located_by_their_field():
    first, second = _translate(_octets("two_fields_one_message"))
    assert [_observation(e)["locator"]["field"] for e in (first, second)] == [0, 1]
    assert [_observation(e)["values"]["locator"]["field"] for e in (first, second)] == [0, 1]
    assert [_observation(e)["quantity"]["code"] for e in (first, second)] == ["0.2.2", "0.2.3"]
    assert first["event_id"] != second["event_id"]
    assert first["residual"]["data"]["local_use"] is None
    assert [e["source"]["record_index"] for e in (first, second)] == [0, 0]


def test_the_jpeg2000_field_is_stated_by_reference_without_a_summary():
    [event] = _translate(_octets("jpeg2000_reference_form"))
    values = _observation(event)["values"]
    assert (values["dtype"], values["summary"], values["scale"], values["offset"]) == (
        "JPEG 2000 codestream of 16-bit values",
        None,
        0.000125,
        1.5,
    )
    assert values["encoding"] == (
        "GRIB2 Code Table 5.0 template 40, Grid point data - JPEG 2000 code stream format: Y = (R "
        "+ X x 2^E) / 10^D with R = 1500.0, E = -3, D = 3; the codestream is not decoded here"
    )
    assert grib2.T_SUMMARY not in event["source"]["transformations"]
    assert (
        bytes.fromhex(_twin("jpeg2000_reference_form")["codestreams"][0])[:4] == b"\xff\x4f\xff\x51"
    )


def test_complex_packing_and_png_state_their_encoding_and_a_bitmap():
    encodings = {
        name: _observation(_translate(_octets(name))[0])["values"]["encoding"]
        for name in ("complex_order_2_with_bitmap", "png_16_bit")
    }
    assert encodings == {
        "complex_order_2_with_bitmap": (
            "GRIB2 Code Table 5.0 template 3, Grid Point Data - Complex Packing and Spatial "
            "Differencing: Y = (R + X x 2^E) / 10^D with R = 550.0, E = 0, D = 1; spatial "
            "differencing of order 2, Code Table 5.5 missing value management 0; a Section 6 "
            "bitmap applies"
        ),
        "png_16_bit": (
            "GRIB2 Code Table 5.0 template 41, Grid point data - Portable Network Graphics (PNG): "
            "Y = (R + X x 2^E) / 10^D with R = 1500.0, E = -3, D = 3"
        ),
    }
    assert _observation(_translate(_octets("png_8_bit"))[0])["values"]["dtype"] == (
        "PNG 8-bit greyscale samples"
    )


# ================================================================== the Lambert footprint

#: PROJ's reading of the six grid points (gdaltransform, GDAL 3.13.3, 2026-10-17): La1/Lo1
#: projected with +proj=lcc +lat_1=57 +lat_2=57 +lon_0=22 on the sphere of the message's radius,
#: plus i x 3000 m east and j x 3000 m north, projected back; ring order (0,0) (1,0) (2,0) (2,1)
#: (1,1) (0,1), closed.
PROJ_RING_6371229 = [
    (22.024776000, 57.013487000),
    (22.074328907, 57.013467432),
    (22.123881736, 57.013428295),
    (22.123971656, 57.040406926),
    (22.074382859, 57.040446091),
    (22.024793984, 57.040465673),
]
PROJ_RING_6367470 = [
    (22.024776000, 57.013487000),
    (22.074358160, 57.013467414),
    (22.123940242, 57.013428237),
    (22.124030258, 57.040422794),
    (22.074412166, 57.040462000),
    (22.024793995, 57.040481600),
]


def _ring(octets: bytes) -> list:
    return _translate(octets)[0]["geometry"]["coordinates"][0]


def _close_to(ring: list, expected: list) -> bool:
    # Rounded to 10^-6 degree by the adapter: within half a unit of PROJ's value, plus slack.
    return (
        len(ring) == len(expected) + 1
        and ring[0] == ring[-1]
        and all(
            abs(lon - e_lon) <= 6e-7 and abs(lat - e_lat) <= 6e-7
            for (lon, lat), (e_lon, e_lat) in zip(ring, expected)
        )
    )


def test_the_lambert_footprint_is_the_grid_points_outline_as_proj_reads_it():
    ring = _ring(_octets("lambert_conformal_simple"))
    assert _close_to(ring, PROJ_RING_6371229), ring
    assert all(round(v, 6) == v for point in ring for v in point)


def test_the_two_named_spheres_take_their_radii_from_code_table_3_2():
    grid = copy.deepcopy(BUILDER.GDAL_FIXTURES["lambert_conformal_simple"]["grid"])
    grid["parameters"]["earth_shape"] = 6  # 6,371,229 m: the same sphere as the fixture's shape 1
    assert _close_to(_ring(_simple_message(grid=grid)), PROJ_RING_6371229)
    grid["parameters"]["earth_shape"] = 0  # 6,367,470 m
    assert _close_to(_ring(_simple_message(grid=grid)), PROJ_RING_6367470)


#: PROJ's reading of a 40 x 20 Lambert grid's outline (gdaltransform, GDAL 3.13.3, 2026-10-17;
#: R5 review 1, F-04): 3 km cells, secant latitudes 55 and 59 N, LoV 22 E, the first point
#: 56.2 N 20.5 E, the 6,371,229 m sphere of shape 6. The first point is projected forward, each
#: outline vertex is that point plus (i x 3000 m, j x 3000 m) and is read back by PROJ. An edge
#: of 39 or 19 cells is cut into 16 equal segments, so the vertices sit at i = 39 s / 16 along
#: the south and north edges and j = 19 s / 16 along the east and west ones, s = 0 to 15.
PROJ_RING_DENSIFIED = [
    (20.500000000, 56.200000000),
    (20.618247453, 56.201387835),
    (20.736503190, 56.202661787),
    (20.854766503, 56.203821844),
    (20.973036684, 56.204867996),
    (21.091313024, 56.205800232),
    (21.209594814, 56.206618546),
    (21.327881344, 56.207322929),
    (21.446171907, 56.207913374),
    (21.564465791, 56.208389877),
    (21.682762289, 56.208752434),
    (21.801060690, 56.209001040),
    (21.919360284, 56.209135694),
    (22.037660362, 56.209156394),
    (22.155960214, 56.209063140),
    (22.274259130, 56.208855934),
    (22.392556401, 56.208534776),
    (22.392887907, 56.240587909),
    (22.393219972, 56.272641282),
    (22.393552600, 56.304694885),
    (22.393885790, 56.336748708),
    (22.394219545, 56.368802742),
    (22.394553867, 56.400856976),
    (22.394888755, 56.432911401),
    (22.395224213, 56.464966007),
    (22.395560241, 56.497020783),
    (22.395896841, 56.529075721),
    (22.396234015, 56.561130810),
    (22.396571763, 56.593186039),
    (22.396910088, 56.625241401),
    (22.397248990, 56.657296883),
    (22.397588471, 56.689352477),
    (22.397928533, 56.721408172),
    (22.278012408, 56.721733753),
    (22.158094569, 56.721943813),
    (22.038175755, 56.722038351),
    (21.918256706, 56.722017366),
    (21.798338161, 56.721880857),
    (21.678420859, 56.721628828),
    (21.558505539, 56.721261278),
    (21.438592941, 56.720778213),
    (21.318683804, 56.720179636),
    (21.198778866, 56.719465553),
    (21.078878866, 56.718635971),
    (20.958984543, 56.717690898),
    (20.839096635, 56.716630341),
    (20.719215881, 56.715454312),
    (20.599343018, 56.714162820),
    (20.479478783, 56.712755879),
    (20.480777792, 56.680707602),
    (20.482074584, 56.648659417),
    (20.483369165, 56.616611334),
    (20.484661539, 56.584563362),
    (20.485951713, 56.552515511),
    (20.487239693, 56.520467791),
    (20.488525483, 56.488420213),
    (20.489809090, 56.456372786),
    (20.491090519, 56.424325520),
    (20.492369775, 56.392278425),
    (20.493646865, 56.360231511),
    (20.494921793, 56.328184788),
    (20.496194565, 56.296138265),
    (20.497465186, 56.264091953),
    (20.498733663, 56.232045861),
]


def test_a_lambert_edge_of_more_than_sixteen_cells_is_densified_to_sixteen_segments():
    grid = _lambert(
        earth_shape=6, nx=40, ny=20, la1=56_200_000, lo1=20_500_000,
        latin1=55_000_000, latin2=59_000_000,
    )  # fmt: skip
    ring = grib2.footprint(grid)
    assert _close_to(ring, PROJ_RING_DENSIFIED), ring
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    assert area > 0


def test_a_lambert_grid_scanned_westward_keeps_a_counter_clockwise_ring():
    grid = copy.deepcopy(BUILDER.GDAL_FIXTURES["lambert_conformal_simple"]["grid"])
    grid["parameters"]["scanning_mode"] = 0xC0  # -i: the first point is the east column
    ring = _ring(_simple_message(grid=grid))
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    assert area > 0 and len(ring) == 7 and ring[0] == ring[-1]
    # The first grid point is now the grid's south-east corner, and two 3 km cells lie west of
    # it (about 0.099 degree of longitude at 57 N): the west column is near 21.9252 E.
    assert [22.024776, 57.013487] in ring
    assert 21.92 < min(lon for lon, _ in ring) < 21.93


def test_a_westward_lat_lon_grid_states_the_same_footprint():
    grid = BUILDER.latlon(3, 2, 21_125_000, 57_125_000, 250_000, scanning_mode=0xC0)
    grid["parameters"]["lo1"], grid["parameters"]["lo2"] = 21_625_000, 21_125_000
    assert _ring(_simple_message(grid=grid)) == [
        [21.125, 57.125], [21.625, 57.125], [21.625, 57.375], [21.125, 57.375], [21.125, 57.125]
    ]  # fmt: skip


# ================================================================== the injected arguments


def test_the_injected_digests_ordinal_and_offset_reach_the_stamp_and_every_locator():
    digest = "a" * 64
    frame = "b" * 64
    events = _translate(
        _octets("two_fields_one_message"),
        source_hash={"algorithm": "sha256", "value": digest},
        frame_sha256=frame,
        message_ordinal=4,
        byte_offset=1234,
    )
    for index, event in enumerate(events):
        assert event["source"]["source_hash"] == {"algorithm": "sha256", "value": digest}
        assert event["source"]["record_index"] == 4
        observation = _observation(event)
        expected = {
            "kind": "grib",
            "message": 4,
            "field": index,
            "byte_offset": 1234,
            "frame_sha256": frame,
            "granule_id": None,
        }
        assert observation["locator"] == observation["values"]["locator"] == expected


@pytest.mark.parametrize(
    "kwargs, text",
    [
        ({"source_hash": {"algorithm": "sha256", "value": "A" * 64}},
         "source_hash is a sha256 digest of 64 lower-case hex digits"),
        ({"frame_sha256": "x"}, "frame_sha256 is 64 lower-case hexadecimal digits"),
        ({"message_ordinal": -1}, "message_ordinal is a non-negative int"),
        ({"message_ordinal": True}, "message_ordinal is a non-negative int"),
        ({"byte_offset": 1.0}, "byte_offset is a non-negative int"),
    ],
)  # fmt: skip
def test_a_malformed_constructor_argument_is_refused(kwargs, text):
    with pytest.raises(ValueError) as raised:
        Grib2Adapter(clock=times.frozen_clock(), **kwargs)
    assert str(raised.value) == text


def test_the_receipt_clock_reaches_received_at_and_nothing_else():
    import datetime as dt

    at = dt.datetime(2026, 4, 29, 6, 40, tzinfo=dt.timezone.utc)
    a = _translate(_octets("zero_width_accumulation"), clock=lambda: at)
    b = _translate(_octets("zero_width_accumulation"))
    assert a[0]["received_at"] == "2026-04-29T06:40:00.000Z" and b[0]["received_at"] == FROZEN
    a[0].pop("received_at"), b[0].pop("received_at")
    assert a == b


def test_a_text_or_a_list_is_not_a_message():
    for payload in ("GRIB", ["GRIB"], 7):
        refusal = _refusal(payload)
        assert str(refusal) == (
            "unsupported-input: a message is handed over as its octets or as its twin in a dict; "
            "text and other types are not taken"
        )


# ================================================================== the bounds


def test_png_rows_are_held_to_the_decompression_bound_before_inflating():
    octets = _octets("mrms_style_png_sentinels")
    # 5 rows of 1 + 4 x 2 octets: 45 octets of rows.
    assert grib2.decode_message(octets, limit=45).stats[0].count == 20
    with pytest.raises(Grib2Refused) as raised:
        grib2.decode_message(octets, limit=44)
    assert str(raised.value) == (
        "png-past-the-decompression-bound: field 0: the PNG's rows inflate to 45 octets, past what "
        "max_decompressed_bytes = 67108864 leaves the message; refused before inflating"
    )
    big = (MALFORMED / "png_rows_past_the_decompression_bound.grb2").read_bytes()
    assert len(big) < 300  # nothing to inflate: the bound is judged on the rows the IHDR implies
    assert str(_refusal(big)) == (
        "png-past-the-decompression-bound: field 0: the PNG's rows inflate to 67112960 octets, "
        "past what max_decompressed_bytes = 67108864 leaves the message; refused before inflating"
    )


def test_the_grid_points_of_one_message_are_held_to_their_bound():
    # Two zero-width fields on an 8192 x 4096 grid: each is MAX_GRID_POINTS exactly, so the
    # first is read and the second is refused before any of its values.
    grid = BUILDER.latlon(8192, 4096, 22_500_000, 58_000_000, 1)
    field = [
        BUILDER.s4_octets(BUILDER.product0(19, 0, 0, 1, 0, 1, 0, 0)),
        BUILDER.s5_octets(BUILDER.representation(0, 33554432, 21, **BUILDER.scaling(0.0, 0, 0, 0))),
        BUILDER.section(6, b"\xff"),
        BUILDER.section(7, b""),
    ]
    one = BUILDER.message(
        0, [BUILDER.s1_octets(BUILDER.identification()), BUILDER.s3_octets(grid), *field]
    )
    assert grib2.decode_message(one).stats[0].count == 33554432
    two = BUILDER.message(
        0, [BUILDER.s1_octets(BUILDER.identification()), BUILDER.s3_octets(grid), *field, *field]
    )
    assert str(_refusal(two)) == (
        "grid-past-the-points-bound: field 1: the message's grids describe more than "
        "MAX_GRID_POINTS = 33554432 points"
    )


def _one_group_order_2(ni: int, nj: int) -> bytes:
    """R5 review 1, F-01: one zero-width group of Ni x Nj points under complex packing, order 2,
    h1 = 5, h2 = 7, minimum 0, the group's 8-bit reference 3, R = 1, E = D = 0. The message is
    214 octets whatever the grid: v(0) = 5, v(1) = 7, v(k) = 3 + 2 v(k-1) - v(k-2), so
    v(k) = 5 + 2k + 3k(k-1)/2 and Y = 1 + v(k)."""
    points = ni * nj
    r = BUILDER.representation(
        3, points, 49, **BUILDER.scaling(1.0, 0, 0, 8),
        group_splitting=1, missing_management=0, primary_missing=None, secondary_missing=None,
        groups=1, group_width_reference=0, group_width_bits=0, group_length_reference=points,
        group_length_increment=1, last_group_length=points, group_length_bits=0,
        spatial_differencing_order=2, spatial_differencing_octets=2,
    )  # fmt: skip
    data = struct.pack(">HHH", BUILDER.sm(5, 2), BUILDER.sm(7, 2), BUILDER.sm(0, 2)) + b"\x03"
    return BUILDER.message(
        0,
        [
            BUILDER.s1_octets(BUILDER.identification()),
            BUILDER.s3_octets(BUILDER.latlon(ni, nj, 22_500_000, 57_000_000, 1)),
            BUILDER.s4_octets(UGRD),
            BUILDER.s5_octets(r),
            BUILDER.section(6, b"\xff"),
            BUILDER.section(7, data),
        ],
    )


def test_two_hundred_and_fourteen_octets_of_complex_packing_decode_the_whole_points_bound():
    # The review's case at MAX_GRID_POINTS: k = 33554431 gives
    # 1 + 5 + 2 x 33554431 + 3 x 33554431 x 33554430 / 2 = 1688849776377863.
    message = _one_group_order_2(8192, 4096)
    assert len(message) == 214
    stats = grib2.decode_message(message).stats[0]
    assert (stats.count, stats.missing, stats.low, stats.high) == (
        33554432, 0, 6.0, 1688849776377863.0
    )  # fmt: skip


def _sixteen_bit_simple(ni: int, nj: int) -> bytes:
    """Simple packing at 16 bits, the codes 0, 1, ..., 65535 over and over, R = E = D = 0."""
    data = struct.pack(">65536H", *range(65536)) * (ni * nj // 65536)
    return _simple_message(
        r=BUILDER.scaling(0.0, 0, 0, 16), points=ni * nj, data=data,
        grid=BUILDER.latlon(ni, nj, 21_125_000, 57_125_000, 1),
    )  # fmt: skip


def _sub_filtered_png(width: int, height: int) -> bytes:
    """The MRMS-style field, 16-bit PNG: every row Sub-filtered with every stated sample 0x0101,
    so each octet of sample k reads (k + 1) mod 256 and the sample 257 x ((k + 1) mod 256).
    Y = (X - 30) / 10: X = 0 is the -3 sentinel ("No Coverage"), twice a row of 512; X = 20
    never occurs; the rest run from 257 (22.7) to 65535 (6550.5)."""
    rows = (b"\x01" + b"\x01\x01" * width) * height
    stream = (
        b"\x89PNG\r\n\x1a\n"
        + BUILDER.png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0))
        + BUILDER.png_chunk(b"IDAT", zlib.compress(rows, 9))
        + BUILDER.png_chunk(b"IEND", b"")
    )
    return BUILDER.message(
        209,
        [
            BUILDER.s1_octets(
                BUILDER.identification(centre=161, data_type=7, reference_time_significance=3)
            ),
            BUILDER.s3_octets(BUILDER.latlon(width, height, 22_500_000, 57_000_000, 1)),
            BUILDER.s4_octets(BUILDER.product0(6, 37, 0, 0, 0, 102, 0, 0)),
            BUILDER.s5_octets(
                BUILDER.representation(41, width * height, 21, **BUILDER.scaling(-30.0, 0, 1, 16))
            ),
            BUILDER.section(6, b"\xff"),
            BUILDER.section(7, stream),
        ],
    )


#: 512 x 512 = 262144 points, four times grib2.CHUNK: (the message's builder, the PNG rows'
#: octets, the summary as count, missing count, minimum, maximum, written by hand above).
HELD = {
    # k = 262143: 1 + 5 + 2 x 262143 + 3 x 262143 x 262142 / 2 = 103078559751.
    "complex": (_one_group_order_2, 0, (262144, 0, 6.0, 103078559751.0)),
    "simple": (_sixteen_bit_simple, 0, (262144, 0, 0.0, 65535.0)),
    "png": (_sub_filtered_png, 512 * (1 + 2 * 512), (262144, 1024, 22.7, 6550.5)),
}


@pytest.mark.parametrize("name", sorted(HELD))
def test_a_field_is_summarised_without_holding_its_values(name):
    """R5 review 1, F-01: before the fix the decode kept one Python int per point (about 44
    octets of memory a point; the 214-octet message above held 1.46 GB). Now a packing hands its
    sink at most CHUNK codes at a time, so what the decode allocates is at most a few copies of
    the message's octets, the PNG's inflated rows (themselves under max_decompressed_bytes) and
    4 MiB, whatever the number of points."""
    build, rows, summary = HELD[name]
    message = build(512, 512)
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = tracemalloc.get_traced_memory()[0]
        stats = grib2.decode_message(message).stats[0]
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        if not tracing:
            tracemalloc.stop()
    assert (stats.count, stats.missing, stats.low, stats.high) == summary
    assert peak < (4 << 20) + 6 * len(message) + rows, peak


def _marks_message(order: int, width: int, points: int, values: bytes) -> bytes:
    """R5 review 2, F-06: one group of `points` values `width` bits wide under complex packing,
    Code Table 5.5 management 2 (all ones primary-missing, all ones less one secondary-missing),
    h1 = 5, h2 = 7 (order 2), minimum 0, the group's 8-bit reference 0, R = E = D = 0."""
    r = BUILDER.representation(
        3, points, 49, **BUILDER.scaling(0.0, 0, 0, 8),
        group_splitting=1, missing_management=2, primary_missing=None, secondary_missing=None,
        groups=1, group_width_reference=width, group_width_bits=0, group_length_reference=points,
        group_length_increment=1, last_group_length=points, group_length_bits=0,
        spatial_differencing_order=order, spatial_differencing_octets=2,
    )  # fmt: skip
    head = (5, 7, 0) if order == 2 else (5, 0)
    data = b"".join(struct.pack(">H", BUILDER.sm(h, 2)) for h in head) + b"\x00" + values
    return BUILDER.message(
        0,
        [
            BUILDER.s1_octets(BUILDER.identification()),
            BUILDER.s3_octets(BUILDER.latlon(points // 512, 512, 22_500_000, 57_000_000, 1)),
            BUILDER.s4_octets(UGRD),
            BUILDER.s5_octets(r),
            BUILDER.section(6, b"\xff"),
            BUILDER.section(7, data),
        ],
    )


#: 2^23 = 8388608 points at one bit (a message of 1 MiB) or 2^21 at two bits (512 KiB), every
#: mark kind alternating with the next: under management 2 a width of one bit makes every code
#: a mark (1 primary, 0 secondary; 0x55 reads 0, 1, 0, 1, ...), and at two bits 3 is primary and
#: 2 secondary (0xEE reads 3, 2, 3, 2), 0 and 1 present. Before the fix each change of mark kind
#: was held as one record until the field had `order` present values (about 143 octets a point:
#: the 1 MiB message held 1.2 GB). The summary is (count, primary, secondary, low, high) or the
#: refusal's code, written by hand from the octets.
NONE = (None, None)
MARKS = {
    # Every code a mark: 4194304 of each kind, nothing present, so no extreme.
    "one bit, order 1": (1, 1, 1 << 23, b"\x55" * (1 << 20), (8388608, 4194304, 4194304) + NONE),
    "one bit, order 2": (2, 1, 1 << 23, b"\x55" * (1 << 20), (8388608, 4194304, 4194304) + NONE),
    # 0x3B reads 0, 3, 2, 3 and 0xB8 reads 2, 3, 2, 0: the first and last codes are present (h1
    # = 5 and h2 = 7 themselves); primary 2 + 2 x 524286 + 1, secondary 1 + 2 x 524286 + 2.
    "two bits, order 2, a value at each end": (
        2, 2, 1 << 21, b"\x3b" + b"\xee" * 524286 + b"\xb8",
        (2097152, 1048575, 1048575, 5.0, 7.0),
    ),
    # One present value, then marks to the end: order 2 needs two.
    "two bits, order 2, one value": (
        2, 2, 1 << 21, b"\x3b" + b"\xee" * 524287, "too-few-values-to-difference"
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(MARKS))
def test_alternating_missing_marks_are_counted_without_holding_a_record_each(name):
    """R5 review 2, F-06: the deferral of the sink until `order` present values are known held
    a record per change of mark kind. Now the codes are first walked, holding nothing, until
    `order` present values are found, so what the decode allocates is bounded as in the test
    above, whatever the number of points and wherever the present values lie."""
    message = _marks_message(*MARKS[name][:4])
    summary = MARKS[name][4]
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = tracemalloc.get_traced_memory()[0]
        try:
            stats = grib2.decode_message(message).stats[0]
            got = (stats.count, stats.primary_missing, stats.secondary_missing)
            got += (stats.low, stats.high)
        except Grib2Refused as refusal:
            got = refusal.code
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        if not tracing:
            tracemalloc.stop()
    assert got == summary
    assert peak < (4 << 20) + 6 * len(message), peak


def test_the_marks_between_the_first_present_values_keep_their_places():
    # The layout above over 1024 points: 0, 3, 2, 3, then 3, 2 to 2, 3, 2, 0. The two present
    # values are h1 and h2 at the two ends, every mark between them `None` in its place.
    message = _marks_message(2, 2, 1024, b"\x3b" + b"\xee" * 254 + b"\xb8")
    assert grib2.field_values(message, 0) == [5.0] + [None] * 1022 + [7.0]


@pytest.mark.parametrize("name", CASES)
def test_the_decode_is_the_same_at_any_chunk_and_inflate_step(name, monkeypatch):
    """Chunks of three codes and inflate steps of one octet put a chunk boundary inside every
    group, run and row of the fixtures: the twin and every value are still the builder's."""
    monkeypatch.setattr(grib2, "CHUNK", 3)
    monkeypatch.setattr(grib2, "INFLATE_STEP", 1)
    octets = _octets(name)
    assert grib2.twin_of(octets) == _twin(name)
    if name in VALUES:
        assert [grib2.field_values(octets, i) for i in range(len(VALUES[name]))] == VALUES[name]


def test_a_seventeenth_field_is_refused_before_it_is_read():
    grid = BUILDER.latlon(3, 2, 24_000_000, 56_000_000, 250_000)
    field = [
        BUILDER.s4_octets(BUILDER.product0(19, 0, 0, 1, 0, 1, 0, 0)),
        BUILDER.s5_octets(BUILDER.representation(0, 6, 21, **BUILDER.scaling(0.0, 0, 0, 0))),
        BUILDER.section(6, b"\xff"),
        BUILDER.section(7, b""),
    ]
    head = [BUILDER.s1_octets(BUILDER.identification()), BUILDER.s3_octets(grid)]
    sixteen = BUILDER.message(0, head + field * 16)
    assert len(_translate(sixteen)) == 16
    seventeen = BUILDER.message(0, head + field * 17)
    # Section 4 of the seventeenth field: 16 + 21 + 72 + 16 x (34 + 21 + 6 + 5) = 1165.
    assert str(_refusal(seventeen)) == (
        "too-many-fields: Section 4 at octet 1165: the message holds more than max_objects = 16 "
        "fields"
    )


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    deep: dict = {}
    node = deep
    for _ in range(20):
        node["x"] = {}
        node = node["x"]
    with pytest.raises(InputTooDeep):
        Grib2Adapter(clock=times.frozen_clock()).to_cdm(deep)


def test_a_twin_is_held_to_its_own_wire_and_to_its_keys():
    twin = _twin("bitmap_simple_packing")
    extra = {**twin, "injected": 1}
    assert str(_refusal(extra)) == (
        "not-a-twin: a dict is the message's twin, exactly: wire_hex, indicator, identification, "
        "local_use, fields, summaries, arrays, codestreams"
    )
    for wire in ("ABCD", "abc", 7):
        assert str(_refusal({**twin, "wire_hex": wire})) == (
            "bad-wire-hex: wire_hex is not lower-case hexadecimal of at most 8388608 octets"
        )
    changed = copy.deepcopy(twin)
    changed["summaries"][0]["max"] = 15000  # an int where the decode states a float
    assert str(_refusal(changed)) == (
        "twin-disagrees: the twin's summaries is not what its wire_hex decodes to"
    )
    changed = copy.deepcopy(twin)
    changed["fields"][0]["grid"]["parameters"]["la1"] += 1
    assert str(_refusal(changed)) == (
        "twin-disagrees: the twin's fields is not what its wire_hex decodes to"
    )


def test_a_refusal_is_a_value_error_that_survives_pickling():
    refusal = _refusal(_octets("simple_packing_latlon")[:-1])
    assert isinstance(refusal, ValueError)
    again = pickle.loads(pickle.dumps(refusal))
    assert (type(again), again.code, str(again)) == (Grib2Refused, refusal.code, str(refusal))
    assert copy.copy(refusal).code == refusal.code


# ================================================================== the malformed set

MALFORMED_REFUSALS = {
    "truncated_message": (
        "truncated-message: Section 0's total length runs past the payload: the message is cut "
        "short"
    ),
    "total_length_short_of_the_payload": (
        "octets-after-message: the payload is longer than Section 0's total length: one message "
        "is one payload"
    ),
    "missing_end_section": (
        "no-end-section: the message does not end with Section 8's four octets '7777'"
    ),
    "grib_edition_1": (
        "grib-edition-1: Section 0 octet 8 says edition 1; GRIB edition 1 (ERA5's archive among "
        "others) is not read"
    ),
    "unknown_packing_template": (
        "unsupported-packing-template: Section 5 at octet 143: data representation template 5.4 "
        "is not 5.0, 5.3, 5.40 or 5.41"
    ),
    "bitmap_count_disagrees": (
        "bitmap-count-disagrees: field 0: Section 5's number of data points is not the bitmap's "
        "set points"
    ),
    "png_crc_failure": "png-crc: field 0: a PNG chunk fails its CRC",
    "png_rows_past_the_decompression_bound": (
        "png-past-the-decompression-bound: field 0: the PNG's rows inflate to 67112960 octets, "
        "past what max_decompressed_bytes = 67108864 leaves the message; refused before inflating"
    ),
    "png_data_past_its_rows": (
        "png-data-past-its-rows: field 0: the PNG's image data inflates past its 45 octets of rows"
    ),
    "grid_template_32769": (
        "unsupported-grid-template: Section 3 at octet 37: grid definition template 3.32769 is not "
        "3.0 or 3.30"
    ),
    "repeated_grid_section": (
        "repeated-grid-section: Section 3 at octet 182: a second Section 3; this module reads one "
        "grid per message and a repeat of Sections 4 to 7 under it"
    ),
}


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_message_is_refused_with_its_code_and_its_whole_text(name):
    assert str(_refusal((MALFORMED / f"{name}.grb2").read_bytes())) == MALFORMED_REFUSALS[name]


def test_the_malformed_set_is_exactly_the_table():
    assert sorted(p.stem for p in MALFORMED.glob("*.grb2")) == sorted(MALFORMED_REFUSALS)


# ================================================================== the structural rules

UGRD = BUILDER.product0(2, 2, 2, 1, 1, 103, 0, 10)
GRID = BUILDER.latlon(3, 2, 21_125_000, 57_125_000, 250_000)
CODES = [20000, 32000, 42000, 0, 6000, 13000]  # W3X2 packed with R 1500, E -3, D 3


def _simple_message(
    *,
    s1=None,
    grid=None,
    product=None,
    r=None,
    points=6,
    data=None,
    s6=None,
    template=0,
    length=21,
    extra=(),
) -> bytes:
    """A one-field message of the simple-packing fixture's literals, any part replaced. Without a
    Section 2, so Section 3 is at octet 37, 4 at 109, 5 at 143, 6 at 164 and 7 at 170."""
    grid = grid or GRID
    sections = [
        BUILDER.s1_octets(s1 or BUILDER.identification()),
        BUILDER.s3_octets(grid),
        BUILDER.s4_octets(product or UGRD),
        BUILDER.s5_octets(
            BUILDER.representation(
                template, points, length, **(r or BUILDER.scaling(1500.0, -3, 3, 16))
            )
        ),
        s6 or BUILDER.section(6, b"\xff"),
        BUILDER.section(7, BUILDER.pack_bits(CODES, 16) if data is None else data),
        *extra,
    ]
    return BUILDER.message(0, sections)


def _put(octets: bytes, at: int, value: bytes) -> bytes:
    return octets[:at] + value + octets[at + len(value) :]


def _grid(**over) -> dict:
    grid = copy.deepcopy(GRID)
    grid["parameters"].update(over)
    return grid


def _lambert(**over) -> dict:
    grid = copy.deepcopy(BUILDER.GDAL_FIXTURES["lambert_conformal_simple"]["grid"])
    grid["parameters"].update(over)
    return grid


def _product8(**over) -> dict:
    p = {
        **BUILDER.product0(1, 8, 2, 1, 0, 1, 0, 0)["parameters"],
        "end_year": 2026, "end_month": 4, "end_day": 29, "end_hour": 7, "end_minute": 0,
        "end_second": 0, "time_ranges": 1, "missing_in_statistical_process": 0,
        "statistical_process": 1, "increment_type": 2, "range_unit": 1, "range_length": 1,
        "increment_unit": 255, "increment": 0,
    }  # fmt: skip
    p.update(over)
    return {"section_length": 58, "coordinate_values": 0, "template": 8, "parameters": p}


def _resized(octets: bytes, at: int, extra: bytes) -> bytes:
    """One octet string added at the end of the section at `at`, its length and the total fixed."""
    length = int.from_bytes(octets[at : at + 4], "big")
    body = octets[16:at] + struct.pack(">I", length + len(extra)) + octets[at + 4 : at + length]
    body += extra + octets[at + length : -4]
    return BUILDER.message(octets[6], [body])


def _sections(*parts: bytes) -> bytes:
    return BUILDER.message(0, list(parts))


S1 = BUILDER.s1_octets(BUILDER.identification())
S3 = BUILDER.s3_octets(GRID)
S4 = BUILDER.s4_octets(UGRD)
S5 = BUILDER.s5_octets(BUILDER.representation(0, 6, 21, **BUILDER.scaling(1500.0, -3, 3, 16)))
S6 = BUILDER.section(6, b"\xff")
S7 = BUILDER.section(7, BUILDER.pack_bits(CODES, 16))
BASE = _simple_message()

STRUCTURE = [
    ("not GRIB", b"GRIC" + BASE[4:], "not-grib",
     "the octets do not begin with Section 0's sixteen octets and 'GRIB'"),
    ("edition 3", _put(BASE, 7, b"\x03"), "unsupported-edition",
     "Section 0 octet 8 is not edition 2"),
    ("a section numbered 9", _put(BASE, 168, b"\x09"), "unknown-section",
     "octet 164: a section number outside 1 to 7 before Section 8"),
    ("Section 7 longer than the message", _put(BASE, 170, b"\x00\x00\xff\xff"),
     "section-past-the-end",
     "Section 7 at octet 170: its length is under five octets or runs past Section 8"),
    ("a section length of 4", _put(BASE, 164, b"\x00\x00\x00\x04"), "section-past-the-end",
     "Section 6 at octet 164: its length is under five octets or runs past Section 8"),
    ("three octets before Section 8", _sections(S1, S3, S4, S5, S6, S7 + b"\x00\x00\x00"),
     "section-past-the-end",
     "octet 187: fewer than five octets remain before Section 8 for a section's length and number"),
    ("Section 4 before Section 3", _sections(S1, S4, S3, S5, S6, S7), "section-out-of-order",
     "Section 4 at octet 37: Section 2 or 3 is required here (Section 0 order)"),
    ("Section 1 twice", _sections(S1, S1, S3, S4, S5, S6, S7), "section-out-of-order",
     "Section 1 at octet 37: Section 2 or 3 is required here (Section 0 order)"),
    ("a second Section 2", _sections(S1, BUILDER.section(2, b""), S3, S4, S5, S6, S7,
                                     BUILDER.section(2, b"")),
     "repeated-local-section",
     "Section 2 at octet 192: a second Section 2; this module reads Sections 4 to 7 repeated, "
     "not 2 to 7"),
    ("Section 2 after Section 3", _sections(S1, S3, BUILDER.section(2, b""), S4, S5, S6, S7),
     "section-out-of-order",
     "Section 2 at octet 109: Section 4 is required here (Section 0 order)"),
    ("the message ends after Section 5", _sections(S1, S3, S4, S5), "incomplete-message",
     "the message ends before a field's Sections 4 to 7 are complete"),
    ("no field", _sections(S1, S3), "incomplete-message",
     "the message holds no field: Section 8 follows before any Section 7"),
    ("Section 1 of 22 octets", _resized(BASE, 16, b"\x00"), "section-1-length",
     "Section 1 at octet 16: Section 1 is not the 21 octets of its fixed layout"),
    ("a predefined grid", _put(BASE, 42, b"\x01"), "predefined-grid",
     "Section 3 at octet 37: the source of grid definition is not 0; a predefined grid is not "
     "read"),
    ("a quasi-regular grid", _put(BASE, 47, b"\x01"), "quasi-regular-grid",
     "Section 3 at octet 37: an optional list of numbers follows the template; a quasi-regular "
     "grid is not read"),
    ("Section 3 of 73 octets", _resized(BASE, 37, b"\x00"), "section-3-length",
     "Section 3 at octet 37: Template 3.0's section is 72 octets and this one is not"),
    ("grid template 3.1", _put(BASE, 49, b"\x00\x01"), "unsupported-grid-template",
     "Section 3 at octet 37: grid definition template 3.1 is not 3.0 or 3.30"),
    ("seven points stated for a 3 x 2 grid", _put(BASE, 43, b"\x00\x00\x00\x07"),
     "grid-points-disagree", "Section 3 at octet 37: the number of data points is not Ni x Nj"),
    ("one column", _simple_message(grid=BUILDER.latlon(1, 2, 21_125_000, 57_125_000, 250_000),
                                   points=2, data=BUILDER.pack_bits([0, 0], 16)),
     "grid-too-small",
     "Section 3 at octet 37: a grid of fewer than two points along an axis has no footprint "
     "Polygon"),
    ("8193 x 4096 points", _simple_message(grid=BUILDER.latlon(8193, 4096, 22_500_000, 58_000_000,
                                                                1)),
     "grid-past-the-points-bound",
     "Section 3 at octet 37: Ni x Nj is more than MAX_GRID_POINTS = 33554432"),
    ("adjacent points in j consecutive", _simple_message(grid=_grid(scanning_mode=0x60)),
     "unsupported-scanning-mode",
     "Section 3 at octet 37: Flag Table 3.4 bits 3 to 8 are set; only the i and j directions are "
     "read"),
    ("a basic angle", _simple_message(grid=_grid(basic_angle=1, basic_angle_subdivisions=1000000)),
     "unsupported-basic-angle",
     "Section 3 at octet 37: a basic angle is stated; only 10^-6 degree units are read"),
    ("La1 at 91 degrees", _simple_message(grid=_grid(la1=91_000_000, la2=91_250_000)),
     "latitude-out-of-range", "Section 3 at octet 37: la1 is not within -90 to 90 degrees"),
    ("Lo1 at 360 degrees", _simple_message(grid=_grid(lo1=360_000_000)),
     "longitude-out-of-range", "Section 3 at octet 37: lo1 is not within 0 to 360 degrees"),
    ("La2 south of La1 scanning north", _simple_message(grid=_grid(la2=56_875_000)),
     "grid-disagrees",
     "Section 3 at octet 37: La2 lies the other way from La1 than the scanning mode's j "
     "direction"),
    ("Di disagrees", _simple_message(grid=_grid(di=200_000)), "grid-disagrees",
     "Section 3 at octet 37: Lo1 to Lo2 is not (Ni - 1) x Di in the scanning direction"),
    ("Dj disagrees", _simple_message(grid=_grid(dj=200_000)), "grid-disagrees",
     "Section 3 at octet 37: La1 to La2 is not (Nj - 1) x Dj"),
    ("corners on one meridian", _simple_message(grid=_grid(lo2=21_125_000, di=0xFFFFFFFF)),
     "grid-disagrees", "Section 3 at octet 37: the corner points do not span an area"),
    ("across 180 degrees", _simple_message(grid=_grid(lo1=179_750_000, lo2=180_250_000)),
     "footprint-crosses-antimeridian",
     "Section 3 at octet 37: the grid crosses 180 degrees; a footprint across the antimeridian is "
     "not stated"),
    ("an ellipsoid under Lambert", _simple_message(grid=_lambert(earth_shape=5)),
     "unsupported-earth-shape",
     "Section 3 at octet 37: Code Table 3.2 shape 5 is not one of the spheres 0, 1 and 6; the "
     "footprint is converted with spherical formulas"),
    ("shape 1 with no radius", _simple_message(grid=_lambert(radius_scaled_value=0)),
     "earth-radius-missing", "Section 3 at octet 37: shape 1 states no usable radius"),
    ("a south-pole projection", _simple_message(grid=_lambert(projection_centre=0x80)),
     "unsupported-projection-centre",
     "Section 3 at octet 37: Flag Table 3.5 is not 0; only a north-pole-centred, one-pole "
     "projection is read"),
    ("southern standard parallels",
     _simple_message(grid=_lambert(latin1=-30_000_000, latin2=-30_000_000, lad=-30_000_000)),
     "unsupported-standard-parallels",
     "Section 3 at octet 37: Latin1 and Latin2 are not both in the northern hemisphere"),
    ("LaD off the standard parallels", _simple_message(grid=_lambert(lad=50_000_000)),
     "lad-not-a-standard-parallel",
     "Section 3 at octet 37: LaD, where Dx and Dy are true, is neither Latin1 nor Latin2"),
    ("Dx of zero", _simple_message(grid=_lambert(dx=0)), "grid-length-missing",
     "Section 3 at octet 37: Dx or Dy is zero or missing"),
    ("product template 4.1", _put(BASE, 116, b"\x00\x01"), "unsupported-product-template",
     "Section 4 at octet 109: product definition template 4.1 is not 4.0 or 4.8"),
    ("coordinate values", _put(BASE, 114, b"\x00\x01"), "coordinate-values",
     "Section 4 at octet 109: coordinate values follow the template; they are not read"),
    ("Section 4 of 35 octets", _resized(BASE, 109, b"\x00"), "section-4-length",
     "Section 4 at octet 109: Template 4.0's section is 34 octets and this one is not "
     "(Template 4.8 is read with one time range)"),
    ("packing template 5.2", _put(BASE, 152, b"\x00\x02"), "unsupported-packing-template",
     "Section 5 at octet 143: data representation template 5.2 is not 5.0, 5.3, 5.40 or 5.41"),
    ("Section 5 of 22 octets", _resized(BASE, 143, b"\x00"), "section-5-length",
     "Section 5 at octet 143: Template 5.0's section is 21 octets and this one is not"),
    ("R is NaN", _simple_message(r=BUILDER.scaling(float("nan"), -3, 3, 16)),
     "reference-value-not-finite", "Section 5 at octet 143: the reference value R is not finite"),
    ("D missing", _put(BASE, 160, b"\xff\xff"), "scale-missing",
     "Section 5 at octet 143: E or D is missing"),
    ("original type 2", _simple_message(r=BUILDER.scaling(1500.0, -3, 3, 16, 2)),
     "unsupported-original-type",
     "Section 5 at octet 143: Code Table 5.1's type of original field values is not 0 or 1"),
    ("33 bits", _simple_message(r=BUILDER.scaling(1500.0, -3, 3, 33)), "bits-out-of-range",
     "Section 5 at octet 143: more than 32 bits per packed value"),
    ("a 4-bit PNG", _simple_message(template=41, r=BUILDER.scaling(1500.0, -3, 3, 4)),
     "unsupported-png-depth",
     "Section 5 at octet 143: Template 5.41's depth is not 8 or 16; only greyscale samples of 8 "
     "and 16 bits are read"),
    ("a predefined bitmap", _simple_message(s6=BUILDER.section(6, b"\x05")), "predefined-bitmap",
     "Section 6 at octet 164: Code Table 6.0 indicator 5 names a predefined bitmap, which is not "
     "read"),
    ("a bitmap of two octets for six points", _simple_message(s6=BUILDER.section(6, b"\x00\xfc\x00")),
     "section-6-length",
     "Section 6 at octet 164: the bitmap is not one bit per Section 3 point, padded to an octet"),
    ("indicator 255 with a bitmap", _simple_message(s6=BUILDER.section(6, b"\xff\xfc")),
     "section-6-length", "Section 6 at octet 164: indicator 255 and a bitmap follows"),
    ("indicator 254 with nothing before it", _simple_message(s6=BUILDER.section(6, b"\xfe")),
     "no-previous-bitmap",
     "Section 6 at octet 164: indicator 254 and no earlier field of this message defines a bitmap "
     "for this grid"),
    ("five points in Section 5", _simple_message(points=5), "point-count-disagrees",
     "field 0: Section 5's number of data points is not Section 3's number of points"),
    ("Section 7 one octet long", _simple_message(data=BUILDER.pack_bits(CODES, 16) + b"\x00"),
     "data-length-disagrees", "field 0: Section 7 is not the octets 6 values of 16 bits occupy"),
    ("D of 400", _simple_message(r=BUILDER.scaling(1500.0, -3, 400, 16)), "scale-out-of-range",
     "field 0: the decimal scale factor D is past 10^300"),
    ("E of 1020", _simple_message(r=BUILDER.scaling(1500.0, 1020, 0, 16)), "value-out-of-range",
     "field 0: a decoded value, (R + X x 2^E) / 10^D, is past what a double holds"),
    ("significance 4", _simple_message(s1=BUILDER.identification(reference_time_significance=4)),
     "unsupported-reference-significance",
     "Section 1 octet 12: Code Table 1.2 significance is not 0 to 3"),
    ("data type 3", _simple_message(s1=BUILDER.identification(data_type=3)),
     "unsupported-data-type",
     "Section 1 octet 21: Code Table 1.4's type of processed data is not 0, 1, 2 or 7; no "
     "product class is ruled for it"),
    ("month 13", _simple_message(s1=BUILDER.identification(month=13)), "bad-reference-time",
     "Section 1 octets 13-19 do not name a date and time"),
    ("a forecast in months", _simple_message(product=BUILDER.product0(2, 2, 2, 3, 1, 103, 0, 10)),
     "unsupported-time-unit",
     "field 0: the forecast time's Code Table 4.4 unit is not 0 (minute), 1 (hour) or 13 "
     "(second)"),
    ("the forecast time missing", _put(BASE, 127, b"\xff\xff\xff\xff"), "forecast-time-missing",
     "field 0: the forecast time is missing"),
    ("an interval ending at 08:00", _simple_message(product=_product8(end_hour=8)),
     "interval-disagrees",
     "field 0: Template 4.8's end of the overall interval is not its start plus the length of "
     "its time range"),
    ("two time ranges stated", _simple_message(product=_product8(time_ranges=2)),
     "unsupported-time-ranges",
     "field 0: Template 4.8 states other than one time range specification"),
    ("an interval ending in month 0", _simple_message(product=_product8(end_month=0)),
     "bad-interval-end", "field 0: Template 4.8 octets 35-41 do not name a date and time"),
    ("a range in years", _simple_message(product=_product8(range_unit=4)),
     "unsupported-time-unit",
     "field 0: the time range's Code Table 4.4 unit is not 0 (minute), 1 (hour) or 13 (second)"),
]  # fmt: skip


@pytest.mark.parametrize("label, build, code, text", STRUCTURE, ids=[row[0] for row in STRUCTURE])
def test_every_structural_rule_refuses_with_its_code_and_its_whole_text(label, build, code, text):
    refusal = _refusal(build)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


# -- complex packing ----------------------------------------------------------------------------

COMPLEX = _octets("complex_order_2_with_bitmap")  # no Section 2: Section 5 at 143, 7 after 6


def _complex_section7_at() -> int:
    position = 16
    while COMPLEX[position + 4] != 7:
        position += int.from_bytes(COMPLEX[position : position + 4], "big")
    return position


COMPLEX_RULES = [
    ("group splitting 2", _put(COMPLEX, 164, b"\x02"), "unsupported-group-splitting",
     "Section 5 at octet 143: Code Table 5.4's group splitting method is not 0 or 1"),
    ("management 3", _put(COMPLEX, 165, b"\x03"), "unsupported-missing-management",
     "Section 5 at octet 143: Code Table 5.5's missing value management is not 0, 1 or 2"),
    ("order 3", _put(COMPLEX, 190, b"\x03"), "unsupported-differencing-order",
     "Section 5 at octet 143: the order of spatial differencing is not 1 or 2"),
    ("descriptors of 5 octets", _put(COMPLEX, 191, b"\x05"), "differencing-octets-out-of-range",
     "Section 5 at octet 143: the octets of each spatial differencing descriptor are not 1 to 4"),
    ("group width bits 33", _put(COMPLEX, 179, b"\x21"), "bits-out-of-range",
     "Section 5 at octet 143: group_width_bits is more than 32"),
    ("no group", _put(COMPLEX, 174, b"\x00\x00\x00\x00"), "group-count-out-of-range",
     "field 0: the number of groups is zero or more than the data points"),
    ("a last group one too long", _put(COMPLEX, 185, b"\x00\x00\x00\x07"),
     "group-lengths-disagree",
     "field 0: the group lengths do not add up to Section 5's number of data points"),
    ("a last group of none", _put(COMPLEX, 185, b"\x00\x00\x00\x00"), "empty-group",
     "field 0: a group of length 0"),
    ("Section 7 one octet long", _resized(COMPLEX, _complex_section7_at(), b"\x00"),
     "data-length-disagrees",
     "field 0: Section 7 is not the octets its descriptors, groups and values occupy"),
    ("Section 7 cut inside the descriptors",
     _put(COMPLEX[: _complex_section7_at()] + BUILDER.section(7, b"\x00\x01") + b"7777", 8,
          struct.pack(">Q", _complex_section7_at() + 7 + 4)),
     "data-length-disagrees", "field 0: Section 7 ends inside the group descriptors"),
]  # fmt: skip


@pytest.mark.parametrize(
    "label, build, code, text", COMPLEX_RULES, ids=[row[0] for row in COMPLEX_RULES]
)
def test_every_complex_packing_rule_refuses_with_its_code_and_its_whole_text(
    label, build, code, text
):
    refusal = _refusal(build)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def _complex_message(r: dict, data: bytes, points: int) -> bytes:
    return _simple_message(
        r=r, template=3, length=49, points=points, data=data,
        grid=BUILDER.latlon(2, 2, 21_125_000, 57_125_000, 250_000),
    )  # fmt: skip


def _complex_r(**over) -> dict:
    r = {
        **BUILDER.scaling(0.0, 0, 0, 2),
        "group_splitting": 1, "missing_management": 1, "primary_missing": None,
        "secondary_missing": None, "groups": 1, "group_width_reference": 2,
        "group_width_bits": 0, "group_length_reference": 4, "group_length_increment": 1,
        "last_group_length": 4, "group_length_bits": 0, "spatial_differencing_order": 2,
        "spatial_differencing_octets": 1,
    }  # fmt: skip
    r.update(over)
    return r


def test_complex_packing_differences_need_as_many_present_values_as_their_order():
    # One group of four 2-bit values, order 2, management 1: the codes 1, 3, 3, 3 are one value
    # and three primary-missing ones (3 = 2^2 - 1); h1 = 5, h2 = 0, minimum 0, one octet each;
    # the group reference (2 bits) 0.
    data = bytes((5, 0, 0)) + BUILDER.pack_bits([0], 2) + BUILDER.pack_bits([1, 3, 3, 3], 2)
    assert str(_refusal(_complex_message(_complex_r(), data, 4))) == (
        "too-few-values-to-difference: field 0: fewer present values than the order of spatial "
        "differencing"
    )
    # Two present values are enough for order 2: they are h1 and h2 themselves.
    data = bytes((5, 7, 0)) + BUILDER.pack_bits([0], 2) + BUILDER.pack_bits([1, 3, 1, 3], 2)
    assert grib2.field_values(_complex_message(_complex_r(), data, 4), 0) == [5.0, None, 7.0, None]


def test_complex_packing_reads_signed_descriptors_and_reconstructs_both_orders_by_hand():
    # Order 1: h1 = -3 (sign bit set), minimum -2; stored 0 (placeholder), 0, 3, 1 give the
    # differences -2, 1, -1: -3, -5, -4, -5.
    data = bytes((0x83, 0x82)) + BUILDER.pack_bits([0], 2) + BUILDER.pack_bits([0, 0, 3, 1], 2)
    r = _complex_r(missing_management=0, spatial_differencing_order=1)
    assert grib2.field_values(_complex_message(r, data, 4), 0) == [-3.0, -5.0, -4.0, -5.0]
    # Order 2: h1 = 10, h2 = 12, minimum -1; stored 0, 0, 1, 2 give second differences 0 and 1:
    # 10, 12, 14 (2 x 12 - 10 + 0), 17 (2 x 14 - 12 + 1).
    data = bytes((10, 12, 0x81)) + BUILDER.pack_bits([0], 2) + BUILDER.pack_bits([0, 0, 1, 2], 2)
    r = _complex_r(missing_management=0)
    assert grib2.field_values(_complex_message(r, data, 4), 0) == [10.0, 12.0, 14.0, 17.0]


def test_a_zero_width_group_is_its_reference_or_wholly_missing():
    # Three groups of two, no bit per value, under management 2 with 3-bit references: the first
    # all ones (7), so wholly primary-missing; the second 7 - 1 = 6, wholly secondary-missing; the
    # third 0, two stored differences of 0. Order 1, h1 = 5, minimum 0: the first present value is
    # h1 and the second 5 + 0 + 0.
    r = _complex_r(
        **BUILDER.scaling(0.0, 0, 0, 3),
        missing_management=2,
        groups=3,
        group_width_reference=0,
        group_length_reference=2,
        last_group_length=2,
        spatial_differencing_order=1,
    )
    data = bytes((5, 0)) + BUILDER.pack_bits([7, 6, 0], 3)
    message = _simple_message(
        r=r, template=3, length=49, points=6, data=data,
        grid=BUILDER.latlon(3, 2, 21_125_000, 57_125_000, 250_000),
    )  # fmt: skip
    assert grib2.field_values(message, 0) == [None, None, None, None, 5.0, 5.0]
    stats = grib2.decode_message(message).stats[0]
    assert (stats.primary_missing, stats.secondary_missing, stats.low, stats.high) == (
        2,
        2,
        5.0,
        5.0,
    )


# -- PNG ----------------------------------------------------------------------------------------

QPE_CODES = BUILDER.codes_of(
    VALUES["mrms_style_png_sentinels"][0], BUILDER.scaling(-30.0, 0, 1, 16)
)


def _png_message(stream: bytes, depth: int = 16, s6=None, points: int = 20) -> bytes:
    return BUILDER.message(
        209,
        [
            BUILDER.s1_octets(
                BUILDER.identification(centre=161, data_type=7, reference_time_significance=3)
            ),
            BUILDER.s3_octets(BUILDER.latlon(4, 5, 22_500_000, 58_000_000, 10_000)),
            BUILDER.s4_octets(BUILDER.product0(6, 37, 0, 0, 0, 102, 0, 0)),
            BUILDER.s5_octets(
                BUILDER.representation(41, points, 21, **BUILDER.scaling(-30.0, 0, 1, depth))
            ),
            s6 or BUILDER.section(6, b"\xff"),
            BUILDER.section(7, stream),
        ],
    )


def _png(width=4, height=5, depth=16, colour=0, interlace=0, idat=None, middle=b"", tail=b""):
    header = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    if idat is None:
        rows = [b"\x00" * (width * depth // 8)] * height
        idat = BUILDER.zlib_stored(BUILDER.png_filter(rows, [0] * height, depth // 8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + BUILDER.png_chunk(b"IHDR", header)
        + middle
        + BUILDER.png_chunk(b"IDAT", idat)
        + BUILDER.png_chunk(b"IEND", b"")
        + tail
    )


ROWS_45 = b"\x00" * 45  # five unfiltered rows of 4 x 2 octets

PNG_RULES = [
    ("a GIF in Section 7", _png_message(b"GIF89a" + b"\x00" * 30), "not-png",
     "field 0: Section 7 does not open with the PNG signature"),
    ("a text chunk", _png_message(_png(middle=BUILDER.png_chunk(b"tEXt", b"a\x00b"))),
     "png-chunk-not-read",
     "field 0: a PNG chunk other than IHDR, then IDAT, then IEND, or out of that order; no other "
     "chunk is read"),
    ("an RGB image", _png_message(_png(colour=2)), "unsupported-png-format",
     "field 0: the PNG is not a non-interlaced 8- or 16-bit greyscale image"),
    ("an interlaced image", _png_message(_png(interlace=1)), "unsupported-png-format",
     "field 0: the PNG is not a non-interlaced 8- or 16-bit greyscale image"),
    ("an 8-bit PNG under a 16-bit template", _png_message(_png(depth=8)), "png-depth-disagrees",
     "field 0: the PNG's bit depth is not Template 5.41's"),
    ("5 x 4 for a 4 x 5 grid", _png_message(_png(width=5, height=4)), "png-geometry-disagrees",
     "field 0: the PNG is not Ni samples wide and Nj rows high"),
    ("filter type 5", _png_message(_png(idat=BUILDER.zlib_stored(b"\x05" + ROWS_45[1:]))),
     "png-bad-filter", "field 0: a PNG row's filter type is not 0 to 4 (row 0)"),
    ("rows cut short", _png_message(_png(idat=BUILDER.zlib_stored(ROWS_45[:-1]))), "png-rows-short",
     "field 0: the PNG's image data ends before its rows are complete"),
    ("a stream without its end", _png_message(_png(idat=BUILDER.zlib_stored(ROWS_45)[:-4])),
     "png-rows-short", "field 0: the PNG's image data ends before its rows are complete"),
    ("not zlib", _png_message(_png(idat=b"\x78\x01\xff\xff\xff\xff")), "png-inflate-corrupt",
     "field 0: the PNG's image data is not a valid zlib stream"),
    ("an octet after the stream", _png_message(_png(idat=BUILDER.zlib_stored(ROWS_45) + b"\x00")),
     "png-octets-after-stream", "field 0: octets follow the PNG's zlib stream"),
    ("no IEND", _png_message(_png()[:-12]), "png-unterminated",
     "field 0: the PNG has no IEND chunk"),
    ("an octet after IEND", _png_message(_png(tail=b"\x00" * 12)), "octets-after-png",
     "field 0: Section 7 holds octets after the PNG's IEND chunk"),
    ("a chunk cut short", _png_message(_png()[:-3]), "png-chunk-cut-short",
     "field 0: a PNG chunk is cut short"),
    ("a chunk length past Section 7", _png_message(_png()[:33] + b"\x7f\xff\xff\xff"
                                                     + _png()[37:]),
     "png-chunk-cut-short",
     "field 0: a PNG chunk's length runs past Section 7 or its type is not four letters"),
]  # fmt: skip


@pytest.mark.parametrize("label, build, code, text", PNG_RULES, ids=[row[0] for row in PNG_RULES])
def test_every_png_rule_refuses_with_its_code_and_its_whole_text(label, build, code, text):
    refusal = _refusal(build)
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def test_every_png_filter_is_reversed_and_the_sentinels_counted():
    # The fixture's five rows use filters 1, 2, 3, 4 and 0; the same samples under one filter
    # each decode to the same values.
    for kind in range(5):
        stream = BUILDER.png(4, 5, 16, QPE_CODES, [kind] * 5)
        assert grib2.field_values(_png_message(stream), 0) == VALUES["mrms_style_png_sentinels"][0]


def test_a_png_under_a_bitmap_is_one_row_of_the_present_points():
    present = [i % 3 != 0 for i in range(20)]  # 13 of 20 points
    codes = [c for c, keep in zip(QPE_CODES, present) if keep]
    stream = BUILDER.png(13, 1, 16, codes, [1])
    bitmap = BUILDER.section(6, b"\x00" + BUILDER.bitmap_octets(present))
    values = grib2.field_values(_png_message(stream, s6=bitmap, points=13), 0)
    expected = VALUES["mrms_style_png_sentinels"][0]
    assert values == [v if keep else None for v, keep in zip(expected, present)]
    wrong = _png_message(BUILDER.png(4, 5, 16, QPE_CODES, [0] * 5), s6=bitmap, points=13)
    assert str(_refusal(wrong)) == (
        "png-geometry-disagrees: field 0: the PNG is not one row of the data points"
    )


def test_a_jpeg2000_section_7_must_open_with_a_codestream():
    message = _simple_message(
        template=40, length=23, data=b"\x00\x00\x00\x00",
        r={**BUILDER.scaling(1500.0, -3, 3, 16), "compression_type": 0,
           "target_compression_ratio": 255},
    )  # fmt: skip
    assert str(_refusal(message)) == (
        "not-a-jpeg2000-codestream: field 0: Section 7 does not open with a JPEG 2000 "
        "codestream's SOC and SIZ markers (FF 4F FF 51)"
    )


def test_indicator_254_reuses_the_bitmap_an_earlier_field_defined():
    present = [True, False, True, True, False, True]
    bitmap = BUILDER.section(6, b"\x00" + BUILDER.bitmap_octets(present))
    r = BUILDER.scaling(1500.0, -3, 3, 16)
    field = [
        BUILDER.s4_octets(UGRD),
        BUILDER.s5_octets(BUILDER.representation(0, 4, 21, **r)),
    ]
    data = BUILDER.section(7, BUILDER.pack_bits([20000, 42000, 0, 13000], 16))
    message = _sections(
        S1, S3, *field, bitmap, data, BUILDER.s4_octets(BUILDER.product0(2, 3, 2, 1, 1, 103, 0, 10)),
        field[1], BUILDER.section(6, b"\xfe"), data,
    )  # fmt: skip
    expected = [4.0, None, 6.75, 1.5, None, 3.125]
    assert [grib2.field_values(message, i) for i in (0, 1)] == [expected, expected]
    twin = grib2.twin_of(message)
    assert [a["bitmap_hex"] for a in twin["arrays"]] == ["b4", None]
    assert [f["bitmap"]["indicator"] for f in twin["fields"]] == [0, 254]


# ================================================================== robustness


def test_a_truncated_message_is_refused_at_every_cut():
    octets = _octets("two_fields_one_message")
    for cut in range(len(octets)):
        with pytest.raises(Grib2Refused):
            grib2.decode_message(octets[:cut])


@pytest.mark.parametrize("name", [c for c in CASES if len(_octets(c)) <= 400])
def test_every_single_octet_change_is_read_or_refused_and_never_a_crash(name):
    """Each octet of a fixture flipped in turn: the adapter translates the result or refuses it
    with its own refusal; no other exception escapes."""
    octets = _octets(name)
    adapter = Grib2Adapter(clock=times.frozen_clock())
    for at in range(len(octets)):
        changed = octets[:at] + bytes((octets[at] ^ 0xFF,)) + octets[at + 1 :]
        try:
            adapter.to_cdm(changed)
        except Grib2Refused:
            pass


def test_the_summary_extremes_are_finite_and_the_scale_is_exact():
    for name in CASES:
        for event in _translate(_octets(name)):
            values = _observation(event)["values"]
            assert math.isfinite(values["scale"]) and math.isfinite(values["offset"])
    # 2^-3 / 10^3 and 1500 / 10^3, each one correctly rounded division.
    assert grib2.scale_and_offset(
        {"reference_value": 1500.0, "binary_scale": -3, "decimal_scale": 3}
    ) == (0.000125, 1.5)
    assert grib2.scale_and_offset(
        {"reference_value": -30.0, "binary_scale": 0, "decimal_scale": -2}
    ) == (100.0, -3000.0)
