"""`iem_n0q`, #31 in the ordinal table: one IEM NEXRAD N0Q composite PNG -> one Event.

Every expectation here is a literal written from the fixture builder's description
(`fixtures/iem_n0q/spec/build_fixtures.py`: the cells, the filter type of each named row, the
palette ramp and the chunks it writes with its own DEFLATE writer, sharing no code with the
adapter or the codec) and from the product's documentation as research-raster F1 quotes it, never
read back from the adapter: a dBZ value is (index - 65) / 2 worked out by hand, the footprint is the
world file's north-west cell centre moved half a cell out and 12200 by 5400 cells of 0.005 degree
from there, an identifier is the uuid5 of the documented namespace and name built here, and every
refusal is its code and its whole text. The twins the builder writes are the decode's expectation:
each is compared with what the adapter decodes from its octets.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/iem_n0q/` and runs the
packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import datetime as dt
import decimal
import json
import pathlib
import pickle
import struct
import uuid
import zlib

import pytest

import synapse_cdm
from synapse_cdm import lossless, manifest, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import iem_n0q
from synapse_cdm.adapters import raster_codec as codec
from synapse_cdm.adapters.iem_n0q import IemN0qAdapter, IemN0qRefused
from synapse_cdm.manifest import LimitKind, UnknownFields
from synapse_cdm.observation_contracts import InjectedTime, contract_of
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "iem_n0q"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
SLOT_BASIS = "IEM archive filename slot, UTC, composite nominal time"
BUILDER = support.load_builder(FIXTURES / "spec" / "build_fixtures.py", "iem_n0q_builder")

CASES = [
    "all_missing_no_gentime",
    "corner_cells_paeth_average",
    "echo_patch_split_idat",
    "ramp_ends_every_filter_type",
]
CELLS = 12200 * 5400


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _payload(name: str) -> bytes:
    return (FIXTURES / f"{name}.png").read_bytes()


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _slot(text: str = "2026-04-29T06:05:00Z", basis: str = SLOT_BASIS) -> InjectedTime:
    return InjectedTime(text, basis)


def _translate(payload, clock=None, **kwargs) -> list[dict]:
    kwargs.setdefault("slot", _slot())
    adapter = IemN0qAdapter(clock=clock or times.frozen_clock(), **kwargs)
    return [o.model_dump(mode="json") for o in adapter.to_cdm(payload)]


def _refusal(payload, **kwargs) -> IemN0qRefused:
    kwargs.setdefault("slot", _slot())
    with pytest.raises(IemN0qRefused) as raised:
        IemN0qAdapter(clock=times.frozen_clock(), **kwargs).to_cdm(payload)
    return raised.value


def _observation(obj: dict) -> dict:
    return obj["payload"]["observation"]


def _png(**fields) -> bytes:
    """A 12200 x 5400 N0Q-shaped PNG from the builder's description and its own writers."""
    spec = BUILDER._n0q(**fields)
    return BUILDER.png(spec, BUILDER.zlib_stream(BUILDER.scanlines(spec)))


def _with_ihdr(octets: bytes, **fields) -> bytes:
    """`octets` with its IHDR rewritten (and its CRC recomputed) from the given fields."""
    names = ("width", "height", "bit_depth", "colour_type", "compression", "filter", "interlace")
    values = dict(zip(names, struct.unpack(">IIBBBBB", octets[16:29])))
    values.update(fields)
    body = struct.pack(">IIBBBBB", *(values[n] for n in names))
    return octets[:8] + BUILDER.chunk(b"IHDR", body) + octets[33:]


def _inflated(octets: bytes) -> bytes:
    """The PNG's image data, inflated by zlib, read straight off the chunk layout."""
    position, data = 8, b""
    while position < len(octets):
        (length,) = struct.unpack(">I", octets[position : position + 4])
        if octets[position + 4 : position + 8] == b"IDAT":
            data += octets[position + 8 : position + 8 + length]
        position += 12 + length
    return zlib.decompress(data)


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["iem_n0q"]
    assert cls is IemN0qAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "iem_n0q",
        "1.0.0",
        "ingest",
        "IEM_N0Q",
    )
    assert iem_n0q.__doc__.splitlines()[0] == (
        "`iem_n0q`, #31 in the ordinal table: one IEM NEXRAD N0Q composite PNG -> CDM, ingest only."
    )
    meta = cls.metadata
    assert (
        meta.format.name,
        meta.binding.value,
        meta.license_class.value,
        meta.maturity.level.value,
        meta.claim_status.value,
        meta.residual.value,
        meta.evidence.available,
    ) == (
        "IEM NEXRAD N0Q composite PNG (W3C PNG, IEM product composite_n0q)",
        "standard-encoding",
        "OPEN",
        "L3",
        "VERIFIED",
        "structured",
        False,
    )
    limits = meta.capabilities.limits
    # L-09: one PNG <= 8 MiB; 80 MiB of rows above the constant grid's 65,885,400; one object.
    assert (
        limits.max_input_bytes,
        limits.max_depth,
        limits.max_objects,
        limits.max_decompressed_bytes,
        limits.max_parse_seconds,
    ) == (8388608, 16, 1, 83886080, None)
    assert sorted(limits.absent_because) == ["max_parse_seconds"]
    assert sorted(limits.declared_because) == [
        "max_decompressed_bytes",
        "max_depth",
        "max_input_bytes",
        "max_objects",
    ]
    for basis in limits.declared_because.values():
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
        )
    # Q7-1's basis for the input bound and L-09's for the rows, quoted.
    assert limits.declared_because["max_input_bytes"].source.startswith(
        "the 2026-09-11 archive listing shows 2M PNGs (HM-01 N0Q row)"
    )
    assert limits.declared_because["max_decompressed_bytes"].source.startswith(
        "IHDR 12200 x 5400 paletted = 65,880,000 B of indices plus 5400 filter octets, "
        "65,885,400 B of filtered rows"
    )
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [getattr(entry, "id", None) for entry in meta.limitations] == [
        "values-by-reference",
        "product-constant-grid",
        "time-is-the-caller-slot",
        "ramp-top-disagreement",
        "identity-from-the-slot",
        "evidence-availability",
    ]
    assert manifest.unsupported_paths(meta.limitations) == ("wire_hex",)
    assert sorted(cls.TRANSFORMS) == ["wire_hex"]
    assert sorted(cls.MAPPINGS) == ["ancillary", "header", "index_summary", "palette"]


def test_the_product_constant_is_the_documented_grid_and_its_outline():
    assert (iem_n0q.WIDTH, iem_n0q.HEIGHT, iem_n0q.BIT_DEPTH, iem_n0q.COLOUR_TYPE) == (
        12200,
        5400,
        8,
        3,
    )
    assert iem_n0q.CELL_DEGREES == 0.005
    assert iem_n0q.WORLD_FILE == (0.005, 0.0, 0.0, -0.005, -126.0, 50.0)
    # The outline, worked in decimal: the north-west cell's centre moved half a cell out, then
    # 12200 cells east and 5400 cells south.
    half, cell = decimal.Decimal("0.0025"), decimal.Decimal("0.005")
    west = decimal.Decimal("-126.0") - half
    north = decimal.Decimal("50.0") + half
    east = west + 12200 * cell
    south = north - 5400 * cell
    assert (str(west), str(north), str(east), str(south)) == (
        "-126.0025",
        "50.0025",
        "-65.0025",
        "23.0025",
    )
    assert (iem_n0q.WEST, iem_n0q.NORTH, iem_n0q.EAST, iem_n0q.SOUTH) == (
        -126.0025,
        50.0025,
        -65.0025,
        23.0025,
    )
    assert iem_n0q.FILTERED_OCTETS == 65885400 == 5400 * (1 + 12200)
    assert iem_n0q.FILTERED_OCTETS < iem_n0q.MAX_DECOMPRESSED_BYTES == 80 * 1024 * 1024
    assert "read as the centre of the north-west cell" in iem_n0q.GRID_BASIS
    assert iem_n0q.SLOT_BASIS == SLOT_BASIS


def test_a_refusal_is_a_value_error_with_its_code_and_survives_pickling():
    err = IemN0qRefused("not-the-n0q-grid", "a size")
    assert isinstance(err, ValueError) and str(err) == "not-the-n0q-grid: a size"
    back = pickle.loads(pickle.dumps(err))
    assert (type(back), back.code, back.text, str(back)) == (
        IemN0qRefused,
        "not-the-n0q-grid",
        "a size",
        "not-the-n0q-grid: a size",
    )


# ================================================================== values: the palette transform

DBZ = [
    # (index, dBZ): (index - 65) / 2, worked by hand; index 0 is missing.
    (0, None),
    (1, -32.0),
    (2, -31.5),
    (64, -0.5),
    (65, 0.0),
    (66, 0.5),
    (100, 17.5),
    (150, 42.5),
    (200, 67.5),
    (245, 90.0),
    (254, 94.5),
    (255, 95.0),
]


@pytest.mark.parametrize(("index", "expected"), DBZ)
def test_each_palette_index_stands_for_its_hand_derived_reflectivity(index, expected):
    assert iem_n0q.dbz(index) == expected
    if expected is not None:
        assert iem_n0q.SCALE * index + iem_n0q.OFFSET == expected


@pytest.mark.parametrize("bad", [-1, 256, True, 65.0, "65", None])
def test_a_value_that_is_not_a_palette_index_is_refused(bad):
    with pytest.raises(ValueError) as raised:
        iem_n0q.dbz(bad)
    assert str(raised.value) == "a palette index is an int from 0 to 255"


# ================================================================== the fixture set


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert sorted(p.name for p in FIXTURES.iterdir() if p.suffix == ".png") == [
        f"{n}.png" for n in CASES
    ]
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        [f"{n}.cdm.json" for n in CASES] + [f"{n}.parsed.cdm.json" for n in CASES]
    )
    assert sorted(p.name for p in MALFORMED.iterdir()) == sorted(
        [*MALFORMED_TABLE, "PROVENANCE.json", "README.md"]
    )
    assert not list(FIXTURES.rglob("*.wld")) and not list(FIXTURES.rglob("*.aux.xml"))


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_fixture_is_the_product_s_real_size(name):
    octets = _payload(name)
    assert octets[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">I4sIIBBBBB", octets[8:29]) == (13, b"IHDR", 12200, 5400, 8, 3, 0, 0, 0)
    assert len(octets) <= iem_n0q.MAX_INPUT_BYTES
    assert len(_inflated(octets)) == 65885400


#: Each named row's filter type, as the builder wrote it, read off the inflated scanlines.
FILTER_TYPES = {
    "ramp_ends_every_filter_type": {2700 + k: k % 5 for k in range(10)},
    "echo_patch_split_idat": {100: 1, 101: 2, 102: 2, 103: 2},
    "corner_cells_paeth_average": {0: 4, 5399: 3},
}


@pytest.mark.parametrize("name", sorted(FILTER_TYPES))
def test_the_fixtures_use_every_filter_type_on_the_rows_the_builder_names(name):
    rows = _inflated(_payload(name))
    for y, kind in FILTER_TYPES[name].items():
        assert rows[y * 12201] == kind, (name, y)
    named = set(FILTER_TYPES[name])
    assert {rows[y * 12201] for y in range(5400) if y not in named} == {0}
    assert {k for table in FILTER_TYPES.values() for k in table.values()} == {0, 1, 2, 3, 4}


#: Cells written by the builder, by (row, column): the indices 0, 1, 65, 66 and 255 among them.
CELL_LITERALS = {
    "ramp_ends_every_filter_type": {
        2700: [65, 66, 255, 1, 66, 65, 255, 1],
        2701: [66, 255, 1, 66, 65, 255, 1, 65],
        2702: [255, 1, 66, 65, 255, 1, 65, 66],
        2703: [1, 66, 65, 255, 1, 65, 66, 255],
        2704: [66, 65, 255, 1, 65, 66, 255, 1],
        2709: [66, 255, 1, 66, 65, 255, 1, 65],
    },
}


def test_every_filter_type_undone_gives_back_the_builder_s_cells():
    image = codec.read_png(_payload("ramp_ends_every_filter_type"), max_decompressed_bytes=1 << 27)
    for y, cells in CELL_LITERALS["ramp_ends_every_filter_type"].items():
        row = image.samples(y)
        assert row[6100:6108] == cells, y
        assert row[6099] == 0 and row[6108] == 0
    corners = codec.read_png(_payload("corner_cells_paeth_average"), max_decompressed_bytes=1 << 27)
    first, last = corners.samples(0), corners.samples(5399)
    assert (first[0], first[12199], last[0], last[12199]) == (100, 150, 200, 255)
    assert sum(1 for v in first if v) == 2 and sum(1 for v in last if v) == 2
    patch = codec.read_png(_payload("echo_patch_split_idat"), max_decompressed_bytes=1 << 27)
    for y in (100, 101, 102, 103):
        assert patch.samples(y)[198:208] == [0, 0, 65, 65, 65, 65, 66, 66, 0, 0]


# ================================================================== decode and twins


@pytest.mark.parametrize("name", CASES)
def test_the_decode_of_each_file_is_the_twin_its_builder_wrote(name):
    assert iem_n0q._same(iem_n0q.twin_of(_payload(name)), _twin(name))


@pytest.mark.parametrize("name", CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    assert _translate(_payload(name)) == _translate(_twin(name))


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    a = json.loads((GOLDEN / f"{name}.cdm.json").read_text())
    b = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text())
    assert a == b
    assert a == json.loads(json.dumps(_translate(_payload(name))))


@pytest.mark.parametrize("name", CASES)
def test_every_fixture_becomes_exactly_one_event(name):
    objects = _translate(_payload(name))
    assert [o["object_kind"] for o in objects] == ["event"]
    assert objects[0]["event_type"] == "ENVIRONMENTAL_OBSERVATION"


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_parked_or_a_declared_limitation(name):
    twin = _twin(name)
    book = lossless.ledger(
        twin,
        _translate(twin),
        IemN0qAdapter.MAPPINGS,
        manifest.unsupported_paths(IemN0qAdapter.metadata.limitations),
    )
    assert book.lost == ()
    assert {entry.category for entry in book.entries} == {"RESIDUAL", "DECLARED_LIMITATION"}


#: Per fixture: (missing count, least index, greatest index, least dBZ, greatest dBZ, gentime).
SUMMARIES = {
    # 10 rows x 8 cells, every one non-zero; least index 1 (-32.0), greatest 255 (95.0).
    "ramp_ends_every_filter_type": (
        CELLS - 80,
        1,
        255,
        -32.0,
        95.0,
        "2026-04-29T06:03:24Z",
    ),
    # 4 rows x (4 cells of 65 and 2 of 66): least 0.0 dBZ, greatest 0.5 dBZ.
    "echo_patch_split_idat": (CELLS - 24, 65, 66, 0.0, 0.5, "2026-04-29T06:03:41Z"),
    # Every cell index 0: no value is stated, so the summary states no extremes.
    "all_missing_no_gentime": (CELLS, None, None, None, None, None),
    # Four corner cells, 100 150 200 255: (100 - 65) / 2 = 17.5 and 95.0.
    "corner_cells_paeth_average": (CELLS - 4, 100, 255, 17.5, 95.0, "2026-04-29T06:04:59Z"),
}


@pytest.mark.parametrize("name", CASES)
def test_each_summary_is_the_hand_counted_one_in_dbz(name):
    missing, least, greatest, low, high, gentime = SUMMARIES[name]
    (event,) = _translate(_payload(name))
    observation = _observation(event)
    assert observation["values"]["summary"] == {
        "count": 65880000,
        "missing_count": missing,
        "min": low,
        "max": high,
    }
    assert event["residual"]["data"]["index_summary"] == {
        "count": 65880000,
        "missing_count": missing,
        "min": least,
        "max": greatest,
    }
    version = observation["product_version"]
    if gentime is None:
        assert version is None
    else:
        assert version == {
            "run": None,
            "version": None,
            "production_time_verbatim": gentime,
            "producer": None,
        }


def _keys_ending_at(document, path="$") -> list[tuple[str, object]]:
    found = []
    if isinstance(document, dict):
        for key, value in document.items():
            if key.endswith("_at"):
                found.append((f"{path}.{key}", value))
            found += _keys_ending_at(value, f"{path}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found += _keys_ending_at(value, f"{path}[{index}]")
    return found


@pytest.mark.parametrize("name", CASES)
def test_gentime_is_in_no_key_ending_at_and_every_such_key_is_the_slot_or_the_receipt(name):
    gentime = SUMMARIES[name][5]
    (event,) = _translate(_payload(name))
    stamps = _keys_ending_at(event)
    assert sorted(stamps) == [
        ("$.observed_at", "2026-04-29T06:05:00.000Z"),
        ("$.received_at", FROZEN),
        ("$.source.observed_at", "2026-04-29T06:05:00.000Z"),
        ("$.validity.observed_at", None),
    ]
    if gentime is not None:
        assert gentime.replace("Z", ".000Z") not in json.dumps(event)
        assert all(value != gentime for _, value in stamps)


def test_the_whole_event_of_one_fixture_is_the_hand_written_one():
    (event,) = _translate(_payload("echo_patch_split_idat"))
    external = "N0Q composite 2026-04-29T06:05:00.000Z"
    window = {"column": 0, "row": 0, "width": 12200, "height": 5400}
    locator = {
        "kind": "raster",
        "frame_sha256": None,
        "granule_id": None,
        "band_file": None,
        "ifd": None,
        "tile": None,
        "window": window,
    }
    assert event["event_id"] == _uuid("event", "IEM_N0Q", external)
    assert event["source_ids"] == [{"system": "IEM_N0Q", "external_id": external}]
    assert (event["observed_at"], event["received_at"], event["severity"]) == (
        "2026-04-29T06:05:00.000Z",
        FROZEN,
        "INFO",
    )
    assert event["validity"] == {
        "effective": {"start": "2026-04-29T06:05:00.000Z", "end": "2026-04-29T06:05:00.000Z"},
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
    }
    assert event["geometry"] == {
        "type": "Polygon",
        "coordinates": [
            [
                [-126.0025, 23.0025],
                [-65.0025, 23.0025],
                [-65.0025, 50.0025],
                [-126.0025, 50.0025],
                [-126.0025, 23.0025],
            ]
        ],
    }
    assert event["related_entities"] == []
    assert _observation(event) == {
        "contract": "gridded-field/1",
        "product_class": "observation",
        "product_version": {
            "run": None,
            "version": None,
            "production_time_verbatim": "2026-04-29T06:03:41Z",
            "producer": None,
        },
        "time": {
            "source_time_system": {"name": "UTC", "stated_by": "caller", "basis": SLOT_BASIS},
            "reference_time": None,
            "reference_time_significance": None,
            "forecast_offset": None,
            "statistical_process": None,
        },
        "locator": locator,
        "quality_flags": [],
        "quality_flags_basis": "the PNG states no quality flag; palette index 0 marks a missing "
        "cell, counted in the summary's missing_count",
        "quantity": {
            "name": "composite reflectivity (N0Q)",
            "code": "composite_n0q",
            "namespace": "IEM raster catalogue (rasters.php?rid=2)",
        },
        "unit": {"unit": "dBZ", "unit_namespace": "IEM raster catalogue (rasters.php?rid=2)"},
        "level": None,
        "datum": None,
        "grid": {
            "namespace": "IEM N0Q composite product constant (research-raster F1, F11)",
            "template": "EPSG:4326",
            "shape": [5400, 12200],
            "scanning_mode": "row 0 is the northernmost, column 0 the westernmost",
            "cell_size": [
                {"value": 0.005, "unit": "degree", "unit_namespace": "EPSG:4326"},
                {"value": 0.005, "unit": "degree", "unit_namespace": "EPSG:4326"},
            ],
            "parameters": {
                "world_file": {
                    "x_cell_size": 0.005,
                    "rotation_y": 0.0,
                    "rotation_x": 0.0,
                    "y_cell_size": -0.005,
                    "north_west_cell_centre_x": -126.0,
                    "north_west_cell_centre_y": 50.0,
                },
                "registration": "the world file's last two terms are the centre of the "
                "north-west cell; the outline lies half a cell outside them",
            },
        },
        "values": {
            "mode": "reference",
            "locator": locator,
            "shape": [5400, 12200],
            "dtype": "8-bit palette index (PNG colour type 3)",
            "encoding": "PNG image data: zlib deflate, filter method 0 (filter types 0 to 4 a row)",
            "scale": 0.5,
            "offset": -32.5,
            "fill": 0,
            "summary": {"count": 65880000, "missing_count": 65879976, "min": 0.0, "max": 0.5},
        },
    }
    source = event["source"]
    assert (
        source["system"],
        source["adapter"],
        source["format_name"],
        source["observed_at"],
        source["source_hash"],
        source["original_id"],
        source["synthetic"],
    ) == (
        "IEM_N0Q",
        "iem_n0q",
        "IEM NEXRAD N0Q composite PNG (W3C PNG, IEM product composite_n0q)",
        "2026-04-29T06:05:00.000Z",
        None,
        None,
        True,
    )
    assert source["transformations"][0].endswith(f" — {SLOT_BASIS}")
    data = event["residual"]["data"]
    assert data["header"] == {
        "width": 12200,
        "height": 5400,
        "bit_depth": 8,
        "colour_type": 3,
        "compression_method": 0,
        "filter_method": 0,
        "interlace_method": 0,
    }
    assert data["ancillary"] == [
        {"chunk": "tRNS", "octets_hex": "00"},
        {"chunk": "tEXt", "keyword": "gentime", "text": "2026-04-29T06:03:41Z"},
    ]
    # The builder's ramp: index 0 black, index i (i, 255 - i, 7i mod 256).
    assert len(data["palette"]) == 256
    assert (data["palette"][0], data["palette"][1], data["palette"][65], data["palette"][255]) == (
        [0, 0, 0],
        [1, 254, 7],
        [65, 190, 199],
        [255, 0, 249],
    )
    # The contract a consumer reads back is the one dumped.
    assert contract_of(IemN0qAdapter.fixture_instance(times.frozen_clock()).to_cdm(
        _payload("echo_patch_split_idat"))[0]).values.summary.max == 0.5  # fmt: skip


def test_a_tIME_chunk_and_a_second_text_chunk_are_kept_verbatim_and_read_for_nothing():
    (event,) = _translate(_payload("corner_cells_paeth_average"))
    # tIME 2026-04-29 06:04:59: 0x07EA, 4, 29 (0x1d), 6, 4, 59 (0x3b).
    assert event["residual"]["data"]["ancillary"] == [
        {"chunk": "tEXt", "keyword": "gentime", "text": "2026-04-29T06:04:59Z"},
        {"chunk": "tEXt", "keyword": "Comment", "text": "synthetic fixture: four corner cells"},
        {"chunk": "tIME", "octets_hex": "07ea041d06043b"},
    ]
    assert event["observed_at"] == "2026-04-29T06:05:00.000Z"


# ================================================================== the slot and identity


def test_the_packaged_fixtures_context_is_the_0605_slot_with_iem_s_basis():
    adapter = IemN0qAdapter.fixture_instance(times.frozen_clock())
    assert adapter._slot.rendered == "2026-04-29T06:05:00.000Z"
    assert adapter._slot.basis == SLOT_BASIS
    assert (
        IemN0qAdapter.fixture_instance(times.frozen_clock()).to_cdm(_payload("all_missing_no_gentime"))[0]
        .model_dump(mode="json") == _translate(_payload("all_missing_no_gentime"))[0]
    )  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        "2026-04-29T06:07:00Z",
        "2026-04-29T06:01:00Z",
        "2026-04-29T06:05:30Z",
        "2026-04-29T06:05:00.5Z",
        "2026-04-29T08:03:00+02:00",
    ],
)
def test_a_slot_off_the_five_minute_grid_is_refused_when_the_adapter_is_built(text):
    with pytest.raises(IemN0qRefused) as raised:
        IemN0qAdapter(clock=times.frozen_clock(), slot=_slot(text))
    assert (raised.value.code, raised.value.text) == (
        "slot-off-the-five-minute-grid",
        "an archive slot is a whole minute divisible by five (YYYYMMDDHHMM, minutes modulo 5); "
        "the instant supplied is not one",
    )


def test_a_slot_with_an_offset_is_read_in_utc_and_its_basis_is_carried():
    (event,) = _translate(
        _payload("all_missing_no_gentime"),
        slot=_slot("2026-04-29T08:10:00+02:00", "a caller's own words for the slot"),
    )
    assert event["observed_at"] == "2026-04-29T06:10:00.000Z"
    assert event["validity"]["effective"] == {
        "start": "2026-04-29T06:10:00.000Z",
        "end": "2026-04-29T06:10:00.000Z",
    }
    assert _observation(event)["time"]["source_time_system"] == {
        "name": "UTC",
        "stated_by": "caller",
        "basis": "a caller's own words for the slot",
    }
    external = "N0Q composite 2026-04-29T06:10:00.000Z"
    assert event["source_ids"][0]["external_id"] == external
    assert event["event_id"] == _uuid("event", "IEM_N0Q", external)


def test_the_slot_is_required_and_is_an_injected_time():
    with pytest.raises(TypeError):
        IemN0qAdapter(clock=times.frozen_clock())
    with pytest.raises(TypeError) as raised:
        IemN0qAdapter(clock=times.frozen_clock(), slot="2026-04-29T06:05:00Z")
    assert str(raised.value) == "slot is an InjectedTime(instant, basis)"


def test_the_caller_s_digest_enters_the_identity_and_the_frame_digest_the_locator():
    digest = "ab" * 32
    frame = "cd" * 32
    (event,) = _translate(
        _payload("echo_patch_split_idat"),
        source_hash={"algorithm": "sha256", "value": digest},
        frame_sha256=frame,
    )
    external = f"N0Q composite 2026-04-29T06:05:00.000Z sha256 {digest}"
    assert event["source_ids"] == [{"system": "IEM_N0Q", "external_id": external}]
    assert event["event_id"] == _uuid("event", "IEM_N0Q", external)
    assert event["source"]["source_hash"] == {"algorithm": "sha256", "value": digest}
    assert _observation(event)["locator"]["frame_sha256"] == frame
    assert _observation(event)["values"]["locator"]["frame_sha256"] == frame


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"source_hash": {"algorithm": "sha256", "value": "AB" * 32}},
            "source_hash is a sha256 digest of 64 lower-case hex digits",
        ),
        (
            {"source_hash": {"algorithm": "md5", "value": "ab" * 32}},
            "source_hash is a sha256 digest of 64 lower-case hex digits",
        ),
        ({"frame_sha256": "ab" * 31}, "frame_sha256 is 64 lower-case hexadecimal digits"),
        ({"frame_sha256": 5}, "frame_sha256 is 64 lower-case hexadecimal digits"),
    ],
)
def test_a_malformed_digest_argument_is_refused(kwargs, message):
    with pytest.raises(ValueError) as raised:
        IemN0qAdapter(clock=times.frozen_clock(), slot=_slot(), **kwargs)
    assert str(raised.value) == message


def test_the_receipt_clock_is_the_only_thing_the_clock_moves():
    late = dt.datetime(2026, 4, 29, 7, 0, tzinfo=dt.timezone.utc)
    a = _translate(_payload("ramp_ends_every_filter_type"))[0]
    b = _translate(_payload("ramp_ends_every_filter_type"), clock=times.frozen_clock(late))[0]
    assert b["received_at"] == "2026-04-29T07:00:00.000Z"
    assert {**b, "received_at": FROZEN} == a


# ================================================================== refusals

MALFORMED_TABLE = {
    "wrong_image_size.png": (
        "not-the-n0q-grid",
        "IHDR states an image size other than the product's 12200 x 5400",
    ),
    "truecolour_colour_type_2.png": (
        "not-the-n0q-grid",
        "IHDR states a bit depth or colour type other than the product's 8-bit indexed colour "
        "(colour type 3)",
    ),
    "four_bit_indices.png": (
        "not-the-n0q-grid",
        "IHDR states a bit depth or colour type other than the product's 8-bit indexed colour "
        "(colour type 3)",
    ),
    "idat_crc_failure.png": ("png-crc", "the IDAT chunk's CRC does not match"),
    "truncated_idat_stream.png": ("png-truncated", "the image data's zlib stream is not complete"),
    "inflates_past_its_rows.png": (
        "png-data-past-its-rows",
        "the image data inflates past its rows",
    ),
    "index_past_the_palette.png": (
        "index-past-the-palette",
        "a cell's index lies past the last entry of PLTE, which the PNG specification makes an "
        "error",
    ),
    "gentime_twice.png": ("gentime-twice", "the file states more than one tEXt gentime chunk"),
}


@pytest.mark.parametrize("name", sorted(MALFORMED_TABLE))
def test_each_malformed_payload_is_refused_with_its_code_and_text(name):
    refused = _refusal((MALFORMED / name).read_bytes())
    assert (refused.code, refused.text) == MALFORMED_TABLE[name]


def test_the_malformed_readme_names_every_payload_and_its_code():
    text = (MALFORMED / "README.md").read_text()
    for name, (code, _) in MALFORMED_TABLE.items():
        assert f"| `{name}` | `{code}` |" in text, name


def test_the_header_is_held_to_the_constant_before_anything_is_inflated(monkeypatch):
    # A header check that ran after inflating would reach the codec's inflater first; it must not.
    def no_inflate(*_args, **_kwargs):
        raise AssertionError("the image data was inflated")

    monkeypatch.setattr(codec, "_png_inflate", no_inflate)
    for name in ("wrong_image_size.png", "truecolour_colour_type_2.png", "four_bit_indices.png"):
        assert _refusal((MALFORMED / name).read_bytes()).code == "not-the-n0q-grid"
    base = _payload("all_missing_no_gentime")
    for fields, code in (
        ({"width": 12201}, "not-the-n0q-grid"),
        ({"height": 5399}, "not-the-n0q-grid"),
        ({"colour_type": 0}, "not-the-n0q-grid"),
        ({"bit_depth": 16, "colour_type": 0}, "not-the-n0q-grid"),
        ({"interlace": 1}, "interlaced"),
        ({"compression": 1}, "bad-ihdr"),
    ):
        assert _refusal(_with_ihdr(base, **fields)).code == code, fields


def test_the_image_data_is_held_to_its_rows_and_the_bound():
    refused = _refusal((MALFORMED / "inflates_past_its_rows.png").read_bytes())
    assert (refused.code, refused.text) == (
        "png-data-past-its-rows",
        "the image data inflates past its rows",
    )
    # The bound the codec is handed is the declared one, and the constant grid's rows lie under it.
    assert IemN0qAdapter.metadata.capabilities.limits.max_decompressed_bytes == 83886080
    assert 5400 * (1 + 12200) == 65885400 < 83886080


def test_a_short_stream_and_other_codec_refusals_reach_the_caller_under_this_module_s_class():
    base = _payload("all_missing_no_gentime")
    cases = [
        (b"GIF89a" + base[6:], "not-a-png"),
        (base[:20], "png-truncated"),
        (base[:-12], "png-truncated"),
        (base + b"\x00", "octets-after-iend"),
        (_png(before_idat=[(b"ZZZZ", b"")]), "unknown-critical-chunk"),
        (_png(palette=None), "bad-palette"),
    ]
    for octets, code in cases:
        assert _refusal(octets).code == code


@pytest.mark.parametrize(
    ("body", "text"),
    [
        (
            b" gentime\x002026-04-29T06:03:24Z",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        ),
        (
            b"gen  time\x00x",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        ),
        (
            b"k" * 80 + b"\x00x",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        ),
        (
            b"gentime-no-separator",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        ),
        (
            b"gen\x07time\x00x",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        ),
        (b"gentime\x00a\x00b", "a tEXt chunk's text holds a NUL"),
    ],
)
def test_a_text_chunk_that_breaks_the_png_rules_is_refused(body, text):
    refused = _refusal(_png(before_idat=[(b"tEXt", body)]))
    assert (refused.code, refused.text) == ("bad-text-chunk", text)


@pytest.mark.parametrize("text", ["", "   ", "x" * 1025])
def test_a_blank_or_overlong_gentime_is_refused(text):
    refused = _refusal(_png(before_idat=[(b"tEXt", b"gentime\x00" + text.encode("latin-1"))]))
    assert (refused.code, refused.text) == (
        "bad-gentime",
        "the tEXt gentime chunk's text is blank or longer than 1024 characters",
    )


def test_a_gentime_of_1024_characters_and_latin_1_text_are_carried_as_written():
    long = "y" * 1024
    (event,) = _translate(
        _png(
            before_idat=[
                (b"tEXt", b"gentime\x00" + long.encode("latin-1")),
                (b"tEXt", "Ort\x00Gro\xdfe".encode("latin-1")),
            ]
        )
    )
    assert _observation(event)["product_version"]["production_time_verbatim"] == long
    assert event["residual"]["data"]["ancillary"][1] == {
        "chunk": "tEXt",
        "keyword": "Ort",
        "text": "Große",
    }


def test_a_palette_short_of_an_index_is_refused_and_one_that_reaches_it_is_read():
    short = BUILDER.palette_ramp(200)
    assert _refusal(_png(palette=short, rows={0: (0, {5: 200})})).code == "index-past-the-palette"
    (event,) = _translate(_png(palette=short, rows={0: (0, {5: 199})}))
    assert _observation(event)["values"]["summary"]["max"] == 67.0


# ================================================================== the dict form


def test_a_dict_is_the_twin_exactly_and_must_agree_with_its_octets():
    twin = _twin("echo_patch_split_idat")
    extra = {**twin, "slot": "202604290605"}
    assert (_refusal(extra).code, _refusal(extra).text) == (
        "not-a-twin",
        "a dict is the file's twin, exactly: wire_hex, header, palette, ancillary, index_summary",
    )
    for bad in ("ABCD", "abc", 7, "zz"):
        refused = _refusal({**twin, "wire_hex": bad})
        assert (refused.code, refused.text) == (
            "bad-wire-hex",
            "wire_hex is not lower-case hexadecimal of at most 8388608 octets",
        )
    for key, value in (
        ("index_summary", {**twin["index_summary"], "max": 255}),
        ("ancillary", []),
        ("palette", twin["palette"][:-1]),
        ("header", {**twin["header"], "width": 12200.0}),
    ):
        refused = _refusal({**twin, key: value})
        assert (refused.code, refused.text) == (
            "twin-disagrees",
            f"the twin's {key} is not what its wire_hex decodes to",
        )
    refused = _refusal("not octets")
    assert (refused.code, refused.text) == (
        "unsupported-input",
        "a file is handed over as its octets or as its twin in a dict; text and other types are "
        "not taken",
    )


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    deep: dict = {}
    node = deep
    for _ in range(17):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(InputTooDeep):
        IemN0qAdapter(clock=times.frozen_clock(), slot=_slot()).to_cdm(
            {"wire_hex": "", "header": deep}
        )
