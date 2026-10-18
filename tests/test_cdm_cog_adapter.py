"""`cog`, #30 in the ordinal table: one GeoTIFF, COG or VRT index -> one Event or one PlanObject.

Every expectation here is a literal written from the fixture builder's literals
(`fixtures/cog/spec/build_fixtures.py`: the grids GDAL was given, the directory layout libtiff's
`tiffdump` read from GDAL's octets, or the script's own VRT and TIFF writers, none sharing code
with the adapter) and the standards, never read back from the adapter: a window value is the grid
literal it was written from, a geographic footprint is the outline worked out by hand from the
grid's corner and cell, a UTM vertex is PROJ's reading of the same point (`gdaltransform`, an
independent implementation, run on 2026-10-17), an identifier is the uuid5 of the documented
namespace and name built here, and every refusal is its code and its whole text. The twins the
builder writes are the decode's expectation: each is compared with what the adapter decodes from
its octets.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/cog/` and runs the
packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import copy
import json
import math
import pathlib
import pickle
import struct
import uuid

import pytest

import synapse_cdm
from synapse_cdm import lossless, manifest, times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import cog
from synapse_cdm.adapters.cog import CogAdapter, CogRefused
from synapse_cdm.manifest import LimitKind, UnknownFields
from synapse_cdm.observation_contracts import InjectedTime
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "cog"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
BUILDER = support.load_builder(FIXTURES / "spec" / "build_fixtures.py", "cog_builder")

TIFF_CASES = [
    "ecostress_shaped_lst_tiled",
    "float32_big_endian_nodata",
    "float32_deflate_nad83",
    "float32_lzw_predictor3",
    "hls_shaped_band_cog",
    "int16_packbits_pixel_is_point",
    "navd88_dem_deflate",
    "utm_tiled_cog_lzw",
]
VRT_CASES = ["compound_navd88_index", "local_sources_index"]
CASES = sorted(TIFF_CASES + VRT_CASES)


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _payload(name: str) -> bytes:
    suffix = ".vrt" if name in VRT_CASES else ".tif"
    return (FIXTURES / f"{name}{suffix}").read_bytes()


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _translate(payload, clock=None, **kwargs) -> list[dict]:
    adapter = CogAdapter(clock=clock or times.frozen_clock(), **kwargs)
    return [o.model_dump(mode="json") for o in adapter.to_cdm(payload)]


def _refusal(payload, **kwargs) -> CogRefused:
    with pytest.raises(CogRefused) as raised:
        CogAdapter(clock=times.frozen_clock(), **kwargs).to_cdm(payload)
    return raised.value


def _observation(obj: dict) -> dict:
    return obj["payload"]["observation"]


#: GDAL_METADATA as GDAL writes it, from (name, value, attributes) items.
def _metadata(*items) -> str:
    lines = ["<GDALMetadata>"]
    for name, value, *attributes in items:
        extra = "".join(f' {k}="{v}"' for k, v in (attributes[0] if attributes else {}).items())
        lines.append(f'  <Item name="{name}"{extra}>{value}</Item>')
    return "\n".join(lines + ["</GDALMetadata>", ""])


def _tiff(extra=(), *, drop=(), values=(1.0, 2.0, 3.0, 4.0), geokeys=None, order="II", **kw):
    """A 2 x 2 Float32 strip at 21.0 E 57.5 N in EPSG:4326, cells of 0.25 degree, written by the
    builder's own TIFF writer, with entries added, replaced or dropped."""
    entries = {tag: (tag, kind, value) for tag, kind, value in BUILDER.base_entries()}
    if geokeys is not None:
        entries[34735] = (34735, "SHORT", geokeys)
    for tag in drop:
        entries.pop(tag, None)
    for tag, kind, value in extra:
        entries[tag] = (tag, kind, value)
    blocks = kw.pop("blocks", None)
    if blocks is None:
        blocks = [BUILDER.float32_block(list(values), order)]
    return BUILDER.tiff_file(list(entries.values()), blocks, order=order, **kw)


def _geokeys(*keys) -> list[int]:
    out = [1, 1, 0, len(keys)]
    for key, value in keys:
        out += [key, 0, 1, value]
    return out


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["cog"]
    assert cls is CogAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == ("cog", "1.0.0", "ingest", "COG")
    assert cog.__doc__.splitlines()[0] == (
        "`cog`, #30 in the ordinal table: one Cloud Optimized GeoTIFF (or GeoTIFF, or a VRT index) "
        "-> CDM,"
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
        "GeoTIFF / Cloud Optimized GeoTIFF (OGC GeoTIFF 1.1, OGC COG 1.0)",
        "standard-encoding",
        "OPEN",
        "L3",
        "VERIFIED",
        "structured",
        False,
    )
    limits = meta.capabilities.limits
    # U-07: one file <= 256 MiB; one 512 x 512 Float32 tile decoded; one object a file.
    assert (
        limits.max_input_bytes,
        limits.max_depth,
        limits.max_objects,
        limits.max_decompressed_bytes,
        limits.max_parse_seconds,
    ) == (268435456, 16, 1, 1048576, None)
    assert sorted(limits.absent_because) == ["max_parse_seconds"]
    assert sorted(limits.declared_because) == [
        "max_decompressed_bytes",
        "max_depth",
        "max_input_bytes",
        "max_objects",
    ]
    for basis in [*limits.declared_because.values(), cog.STRUCTURE_BOUNDS_BASIS]:
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
        )
    # The brief's wording for the input bound, U-07's basis figures.
    assert limits.declared_because["max_input_bytes"].source.startswith(
        "3DEP n41w074 165,776,270 B and CUDEM tiles 150-217 MB (research-raster F5/F6)"
    )
    assert "1,048,576 octets" in limits.declared_because["max_decompressed_bytes"].source
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    ids = [getattr(entry, "id", None) for entry in meta.limitations]
    assert ids == [
        "values-by-reference",
        "payload-octets-by-reference",
        "no-source-time",
        "header-and-one-window",
        "coordinate-systems-read",
        "tiff-forms-read",
        "vrt-index-only",
        "identity-from-what-the-file-states",
        "evidence-availability",
    ]
    assert manifest.unsupported_paths(meta.limitations) == ("arrays", "wire_hex")
    assert sorted(cls.TRANSFORMS) == ["arrays", "wire_hex"]
    assert sorted(cls.MAPPINGS) == [
        "gdal_metadata",
        "geokeys",
        "header",
        "ifds",
        "vertical",
        "vrt",
        "window",
    ]
    assert (cog.MAX_IFDS, cog.MAX_ENTRIES, cog.MAX_VALUE_OCTETS, cog.MAX_TOTAL_VALUE_OCTETS) == (
        64,
        128,
        1048576,
        4194304,
    )
    assert cog.MAX_VRT_ELEMENTS == 65536


def test_a_refusal_is_a_value_error_with_its_code_and_survives_pickling():
    err = CogRefused("remote-source", "a source")
    assert isinstance(err, ValueError) and str(err) == "remote-source: a source"
    back = pickle.loads(pickle.dumps(err))
    assert (type(back), back.code, back.text, str(back)) == (
        CogRefused,
        "remote-source",
        "a source",
        "remote-source: a source",
    )


# ================================================================== the fixture set


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    payloads = sorted(p.name for p in FIXTURES.iterdir() if p.suffix in (".tif", ".vrt"))
    assert payloads == sorted([f"{n}.tif" for n in TIFF_CASES] + [f"{n}.vrt" for n in VRT_CASES])
    assert len(CASES) == 10
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(
        [f"{n}.cdm.json" for n in CASES] + [f"{n}.parsed.cdm.json" for n in CASES]
    )


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


def test_every_stated_position_lies_in_the_baltic_rectangle():
    for path in sorted(GOLDEN.iterdir()):
        assert support.positions_outside_the_rectangle(json.loads(path.read_text())) == [], path


MALFORMED_TABLE = {
    "bigtiff_header.tif": (
        "bigtiff",
        "the header states BigTIFF (version 43), which this codec does not read",
    ),
    "truncated_ifd.tif": ("ifd-past-the-end", "IFD 0's entries run past the end of the file"),
    "tile_offset_past_the_end.tif": (
        "block-past-the-end",
        "IFD 0: block 0 does not lie inside the file",
    ),
    "jpeg_compression.tif": ("unsupported-compression", "IFD 0: JPEG compression is not read"),
    "unsupported_crs.tif": (
        "unsupported-crs",
        "IFD 0: ProjectedCRSGeoKey names a system outside the closed set (EPSG:4326, "
        "EPSG:4269, the WGS84 UTM zones)",
    ),
    "tile_inflates_past_its_size.tif": (
        "block-inflates-past-its-size",
        "IFD 0 block 0 inflates past the octets its size implies",
    ),
    "tile_past_the_decompression_bound.tif": (
        "block-past-the-decompression-bound",
        "IFD 0: block 0 decodes to more than 1048576 octets; refused before anything is "
        "decompressed",
    ),
    "ifd_loop.tif": ("ifd-loop", "IFD 1 points back at an IFD already read"),
    "vsicurl_source.vrt": (
        "remote-source",
        "the VRT's band 1 source 0 names a GDAL /vsicurl/ path; a source is never opened, and a "
        "remote one would make a reader a network client",
    ),
    "entity_declaration.vrt": ("vrt-dtd", "the VRT is refused by the XML guard (dtd)"),
}


def test_the_malformed_set_is_exactly_the_table_and_each_is_refused_as_its_readme_says():
    names = sorted(
        p.name for p in MALFORMED.iterdir() if p.name not in ("PROVENANCE.json", "README.md")
    )
    assert names == sorted(MALFORMED_TABLE)
    readme = (MALFORMED / "README.md").read_text()
    for name, (code, text) in MALFORMED_TABLE.items():
        err = _refusal((MALFORMED / name).read_bytes())
        assert (err.code, str(err)) == (code, f"{code}: {text}"), name
        assert f"| `{name}` | `{code}` |" in readme
    assert support.provenance_problems(FIXTURES) == []


def test_the_truncated_directory_is_cut_after_its_fifth_of_twelve_entries():
    octets = (MALFORMED / "truncated_ifd.tif").read_bytes()
    assert len(octets) == 8 + 2 + 12 * 5
    assert struct.unpack("<H", octets[8:10]) == (12,)


# ================================================================== decode and twins


@pytest.mark.parametrize("name", CASES)
def test_the_decode_of_each_file_is_the_twin_its_builder_wrote(name):
    assert cog._same(cog.twin_of(_payload(name)), _twin(name))


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
def test_every_fixture_becomes_exactly_one_object(name):
    objects = _translate(_payload(name))
    kinds = {"ecostress_shaped_lst_tiled": "event", "hls_shaped_band_cog": "event"}
    assert [o["object_kind"] for o in objects] == [kinds.get(name, "plan_object")]


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_parked_or_a_declared_limitation(name):
    twin = _twin(name)
    book = lossless.ledger(
        twin,
        _translate(twin),
        CogAdapter.MAPPINGS,
        manifest.unsupported_paths(CogAdapter.metadata.limitations),
    )
    assert book.lost == ()
    categories = {entry.category for entry in book.entries}
    assert categories <= {"RESIDUAL", "DECLARED_LIMITATION"}
    assert "DECLARED_LIMITATION" in categories


# ================================================================== windows, against the grids


WINDOWS = {
    # (width, height, count, missing, min, max, the values when carried)
    "float32_lzw_predictor3": (
        3,
        3,
        9,
        0,
        12.5,
        21.75,
        [12.5, 13.25, 14.0, 15.5, 16.75, 18.0, 19.25, 20.5, 21.75],
    ),
    "float32_deflate_nad83": (
        3,
        3,
        9,
        0,
        -3.5,
        11.5,
        [-3.5, -1.25, 0.0, 2.75, 4.5, 6.25, 8.0, 9.75, 11.5],
    ),
    "int16_packbits_pixel_is_point": (4, 2, 8, 0, -3, 1200, [7, 7, 7, 7, 7, -3, -3, 1200]),
    # Tile 0 of 10 + 0.5 r + 0.25 c: r and c from 0 to 127, so 10 to 10 + 63.5 + 31.75.
    "utm_tiled_cog_lzw": (128, 128, 16384, 0, 10.0, 105.25, None),
    "navd88_dem_deflate": (
        4,
        3,
        12,
        1,
        -12.5,
        15.75,
        [-12.5, -7.25, -2.0, 1.5, None, 3.25, 5.0, 8.75, 10.5, 12.25, 14.0, 15.75],
    ),
    # Tile 0 of 1000 + 3 r + 2 c with five nodata cells in row 0: the least is r 1, c 0 = 1003,
    # the most r = c = 127 = 1000 + 381 + 254.
    "hls_shaped_band_cog": (128, 128, 16384, 5, 1003, 1635, None),
    # The first strip of two rows: [1.5, nodata, 2.5, NaN] and [3.0, 3.5, nodata, 4.5].
    "float32_big_endian_nodata": (
        4,
        2,
        8,
        3,
        1.5,
        4.5,
        [1.5, None, 2.5, None, 3.0, 3.5, None, 4.5],
    ),
}


@pytest.mark.parametrize("name", sorted(WINDOWS))
def test_each_window_is_block_0_of_its_grid_literal(name):
    width, height, count, missing, low, high, values = WINDOWS[name]
    window = cog.decode_tiff(_payload(name))["window"]
    assert (window["column"], window["row"], window["width"], window["height"]) == (
        0,
        0,
        width,
        height,
    )
    assert (window["count"], window["missing_count"], window["min"], window["max"]) == (
        count,
        missing,
        low,
        high,
    )
    assert window["values"] == values


def test_the_ecostress_shaped_window_is_its_8_by_8_image_inside_a_16_by_16_tile():
    window = cog.decode_tiff(_payload("ecostress_shaped_lst_tiled"))["window"]
    expected = [
        None if (r, c) == (2, 3) else 280 + 0.25 * r + 0.5 * c for r in range(8) for c in range(8)
    ]
    assert window["values"] == expected
    assert (window["width"], window["height"], window["count"], window["missing_count"]) == (
        8,
        8,
        64,
        1,
    )
    assert (window["min"], window["max"]) == (280.0, 285.25)
    assert window["missing_mechanism"] == "GDAL_NODATA (TIFF tag 42113): nan"


def test_each_missing_mechanism_is_named_and_a_nan_beside_a_number_nodata_is_both():
    assert (
        cog.decode_tiff(_payload("float32_big_endian_nodata"))["window"]["missing_mechanism"]
        == "GDAL_NODATA (TIFF tag 42113): -9999; a NaN sample, which states no number"
    )
    assert cog.decode_tiff(_payload("navd88_dem_deflate"))["window"]["missing_mechanism"] == (
        "GDAL_NODATA (TIFF tag 42113): -99999"
    )
    assert (
        cog.decode_tiff(_payload("float32_lzw_predictor3"))["window"]["missing_mechanism"] is None
    )
    no_nodata_nan = _tiff(values=(math.nan, 1.0, 2.0, 3.0))
    window = cog.decode_tiff(no_nodata_nan)["window"]
    assert (window["values"], window["missing_mechanism"]) == (
        [None, 1.0, 2.0, 3.0],
        "a NaN sample, which states no number",
    )


def test_a_sparse_block_0_is_its_nodata_and_without_nodata_is_refused():
    # A sparse block states offset 0 and count 0 (GDAL's SPARSE_OK) and no octet.
    sparse = _tiff([(42113, "ASCII", "-9999"), (273, "LONG", [0]), (279, "LONG", [0])], blocks=[])
    window = cog.decode_tiff(sparse)["window"]
    assert (window["values"], window["missing_count"], window["min"]) == ([None] * 4, 4, None)
    assert window["missing_mechanism"] == "GDAL_NODATA (TIFF tag 42113): -9999"
    err = _refusal(_tiff([(273, "LONG", [0]), (279, "LONG", [0])], blocks=[]))
    assert str(err) == (
        "sparse-block-without-nodata: IFD 0: block 0 is sparse and the file states no "
        "GDAL_NODATA to fill it with"
    )


def test_an_infinite_sample_and_a_nodata_that_is_no_number_are_refused():
    err = _refusal(_tiff(values=(1.0, math.inf, 2.0, 3.0)))
    assert str(err) == "sample-not-finite: IFD 0: block 0 holds an infinite sample"
    err = _refusal(_tiff([(42113, "ASCII", "none")]))
    assert str(err) == "bad-nodata: IFD 0: GDAL_NODATA is not a decimal number or nan"
    err = _refusal(_tiff([(42113, "ASCII", "1e999")]))
    assert str(err) == "bad-nodata: IFD 0: GDAL_NODATA names no number a double holds"


def test_a_float32_nodata_is_compared_as_float32_stores_it():
    # 0.1 is not a Float32; the sample holding 0.1 as Float32 equals the nodata "0.1".
    window = cog.decode_tiff(_tiff([(42113, "ASCII", "0.1")], values=(0.1, 1.0, 2.0, 3.0)))[
        "window"
    ]
    assert window["values"][0] is None and window["missing_count"] == 1


# ================================================================== footprints

#: Worked out by hand from each grid's west and south corner, its cell and its size; the
#: PixelIsPoint grid's ASCII extent is the same outline (GDAL put its tiepoint at the first
#: cell's centre, 20.625 E 56.625 N, half a cell in).
GEOGRAPHIC_RINGS = {
    "float32_lzw_predictor3": (21.0, 57.0, 21.75, 57.75),
    "float32_deflate_nad83": (22.0, 57.5, 22.375, 57.875),
    "int16_packbits_pixel_is_point": (20.5, 56.25, 21.5, 56.75),
    "navd88_dem_deflate": (23.0, 57.25, 23.25, 57.4375),
    "float32_big_endian_nodata": (20.5, 56.0, 21.0, 56.5),
    "local_sources_index": (21.0, 57.0, 22.5, 57.75),
    "compound_navd88_index": (23.0, 57.25, 23.5, 57.5),
}


@pytest.mark.parametrize("name", sorted(GEOGRAPHIC_RINGS))
def test_a_geographic_footprint_is_the_cells_outline_worked_out_by_hand(name):
    west, south, east, north = GEOGRAPHIC_RINGS[name]
    (obj,) = _translate(_payload(name))
    assert obj["geometry"] == {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


#: PROJ's reading (gdaltransform, GDAL 3.13.3, 2026-10-17) of every densified vertex of each UTM
#: footprint, counter-clockwise from the south-west corner: 16 segments an edge for the 256-cell
#: grids, 8 for the 8-cell one.
PROJ_UTM_COG = [
    (20.5058547180102, 57.0225085776879),
    (20.5137607164057, 57.0225395251798),
    (20.5216667305802, 57.0225699735611),
    (20.5295727602772, 57.0225999228298),
    (20.5374788052403, 57.0226293729839),
    (20.5453848652129, 57.0226583240213),
    (20.5532909399384, 57.02268677594),
    (20.5611970291605, 57.0227147287382),
    (20.5691031326225, 57.0227421824139),
    (20.5770092500679, 57.0227691369652),
    (20.5849153812402, 57.0227955923903),
    (20.592821525883, 57.0228215486875),
    (20.6007276837395, 57.0228470058549),
    (20.6086338545534, 57.0228719638907),
    (20.616540038068, 57.0228964227934),
    (20.6244462340269, 57.0229203825612),
    (20.6323524421734, 57.0229438431925),
    (20.6323098775525, 57.0272558114328),
    (20.6322673009958, 57.0315677766629),
    (20.6322247124987, 57.0358797388829),
    (20.6321821120566, 57.040191698093),
    (20.6321394996648, 57.0445036542935),
    (20.6320968753188, 57.0488156074846),
    (20.6320542390138, 57.0531275576664),
    (20.6320115907452, 57.0574395048391),
    (20.6319689305085, 57.0617514490029),
    (20.6319262582989, 57.066063390158),
    (20.6318835741118, 57.0703753283047),
    (20.6318408779426, 57.0746872634431),
    (20.6317981697865, 57.0789991955734),
    (20.6317554496391, 57.0833111246958),
    (20.6317127174955, 57.0876230508106),
    (20.6316699733512, 57.0919349739178),
    (20.6237490896444, 57.0919114516514),
    (20.6158282182012, 57.0918874289372),
    (20.6079073592797, 57.0918629057769),
    (20.5999865131381, 57.0918378821722),
    (20.5920656800344, 57.0918123581248),
    (20.5841448602267, 57.0917863336365),
    (20.5762240539734, 57.0917598087089),
    (20.5683032615323, 57.091732783344),
    (20.5603824831618, 57.0917052575436),
    (20.5524617191199, 57.0916772313095),
    (20.5445409696646, 57.0916487046437),
    (20.5366202350542, 57.0916196775481),
    (20.5286995155468, 57.0915901500248),
    (20.5207788114003, 57.0915601220756),
    (20.5128581228731, 57.0915295937028),
    (20.5049374502231, 57.0914985649083),
    (20.5049949002093, 57.0871867133943),
    (20.5050523340663, 57.0828748588562),
    (20.5051097518006, 57.0785630012938),
    (20.5051671534183, 57.074251140707),
    (20.5052245389256, 57.0699392770955),
    (20.5052819083289, 57.0656274104592),
    (20.5053392616343, 57.0613155407978),
    (20.5053965988482, 57.0570036681112),
    (20.5054539199767, 57.0526917923993),
    (20.5055112250261, 57.0483799136617),
    (20.5055685140027, 57.0440680318983),
    (20.5056257869126, 57.0397561471089),
    (20.505683043762, 57.0354442592934),
    (20.5057402845573, 57.0311323684515),
    (20.5057975093047, 57.0268204745831),
]
PROJ_HLS = [
    (21.3270713132574, 56.7535451213338),
    (21.3349208745617, 56.7535242872789),
    (21.3427704251791, 56.7535029591563),
    (21.3506199648592, 56.7534811369672),
    (21.3584694933515, 56.7534588207133),
    (21.3663190104056, 56.7534360103959),
    (21.374168515771, 56.7534127060166),
    (21.3820180091974, 56.7533889075771),
    (21.3898674904343, 56.7533646150788),
    (21.3977169592312, 56.7533398285235),
    (21.4055664153378, 56.7533145479128),
    (21.4134158585036, 56.7532887732483),
    (21.4212652884782, 56.7532625045319),
    (21.4291147050112, 56.7532357417654),
    (21.4369641078521, 56.7532084849504),
    (21.4448134967506, 56.7531807340889),
    (21.4526628714562, 56.7531524891827),
    (21.4527147427411, 56.7574645990421),
    (21.452766628475, 56.7617767058684),
    (21.4528185286631, 56.7660888096619),
    (21.4528704433113, 56.7704009104226),
    (21.4529223724249, 56.7747130081509),
    (21.4529743160095, 56.7790251028468),
    (21.4530262740708, 56.7833371945106),
    (21.4530782466142, 56.7876492831424),
    (21.4531302336454, 56.7919613687425),
    (21.4531822351699, 56.796273451311),
    (21.4532342511933, 56.8005855308481),
    (21.4532862817212, 56.8048976073541),
    (21.4533383267592, 56.809209680829),
    (21.4533903863128, 56.8135217512731),
    (21.4534424603876, 56.8178338186866),
    (21.4534945489892, 56.8221458830696),
    (21.4456307537992, 56.8221742018705),
    (21.4377669443287, 56.8222020253342),
    (21.4299031208298, 56.822229353459),
    (21.4220392835542, 56.822256186243),
    (21.4141754327541, 56.8222825236843),
    (21.4063115686814, 56.8223083657812),
    (21.398447691588, 56.8223337125319),
    (21.3905838017259, 56.8223585639348),
    (21.3827198993471, 56.8223829199881),
    (21.3748559847036, 56.8224067806902),
    (21.3669920580472, 56.8224301460395),
    (21.3591281196302, 56.8224530160344),
    (21.3512641697043, 56.8224753906734),
    (21.3434002085215, 56.8224972699549),
    (21.335536236334, 56.8225186538775),
    (21.3276722533936, 56.8225395424397),
    (21.3276346160501, 56.8182274137451),
    (21.3275969892034, 56.8139152820348),
    (21.3275593728496, 56.8096031473086),
    (21.3275217669844, 56.8052910095663),
    (21.327484171604, 56.8009788688077),
    (21.3274465867042, 56.7966667250327),
    (21.327409012281, 56.792354578241),
    (21.3273714483305, 56.7880424284324),
    (21.3273338948486, 56.7837302756068),
    (21.3272963518312, 56.779418119764),
    (21.3272588192743, 56.7751059609037),
    (21.327221297174, 56.7707937990257),
    (21.3271837855261, 56.76648163413),
    (21.3271462843268, 56.7621694662162),
    (21.3271087935719, 56.7578572952842),
]
PROJ_ECOSTRESS = [
    (24.0229693028557, 57.1678393509688),
    (24.0241252604335, 57.1678667874043),
    (24.0252812200805, 57.1678942132023),
    (24.0264371817957, 57.1679216283627),
    (24.0275931455784, 57.1679490328855),
    (24.0287491114279, 57.1679764267707),
    (24.0299050793433, 57.1680038100183),
    (24.0310610493238, 57.1680311826281),
    (24.0322170213686, 57.1680585446001),
    (24.0321666630229, 57.1686865279008),
    (24.0321163026135, 57.1693145111096),
    (24.0320659401404, 57.1699424942265),
    (24.0320155756034, 57.1705704772515),
    (24.0319652090024, 57.1711984601847),
    (24.0319148403373, 57.171826443026),
    (24.031864469608, 57.1724544257754),
    (24.0318140968143, 57.1730824084329),
    (24.0306579683898, 57.1730550412233),
    (24.0295018420306, 57.1730276633738),
    (24.0283457177375, 57.1730002748846),
    (24.0271895955112, 57.1729728757557),
    (24.0260334753526, 57.1729454659872),
    (24.0248773572624, 57.172918045579),
    (24.0237212412414, 57.1728906145313),
    (24.0225651272906, 57.172863172844),
    (24.0226156564829, 57.1722351954318),
    (24.0226661836046, 57.1716072179275),
    (24.0227167086556, 57.1709792403312),
    (24.0227672316361, 57.1703512626428),
    (24.0228177525463, 57.1697232848624),
    (24.0228682713862, 57.1690953069899),
    (24.022918788156, 57.1684673290254),
]

UTM_RINGS = {
    "utm_tiled_cog_lzw": PROJ_UTM_COG,
    "hls_shaped_band_cog": PROJ_HLS,
    "ecostress_shaped_lst_tiled": PROJ_ECOSTRESS,
}


def _area(ring) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))


@pytest.mark.parametrize("name", sorted(UTM_RINGS))
def test_a_utm_footprint_is_proj_s_reading_of_every_densified_vertex(name):
    (obj,) = _translate(_payload(name))
    ring = obj["geometry"]["coordinates"][0]
    proj = UTM_RINGS[name]
    assert len(ring) == len(proj) + 1 and ring[-1] == ring[0]
    for (lon, lat), (plon, plat) in zip(ring, proj):
        # The adapter rounds to 10^-6 degree; PROJ prints fifteen digits.
        assert abs(lon - plon) <= 6e-7 and abs(lat - plat) <= 6e-7, ((lon, lat), (plon, plat))
        assert lon == round(lon, 6) and lat == round(lat, 6)
    assert _area(ring) > 0, "counter-clockwise"


@pytest.mark.parametrize(
    "easting,northing,zone,proj",
    [
        # PROJ (gdaltransform) on 2026-10-17: EPSG:32733 and EPSG:32635 points, the southern
        # northings freed of their 10 000 000 m false northing.
        (500000.0, 4000000.0 - 10000000.0, 33, (15.0, -54.1481041038695)),
        (166021.4431, 1000000.0 - 10000000.0, 33, (-3.58129224378194, -80.5777876432212)),
        (833978.5569, 9000000.0 - 10000000.0, 33, (18.0374661325037, -9.03398046006381)),
        (320000.0, 6340000.0, 35, (24.0229693028557, 57.1678393509688)),
        (680000.0, 9300000.0, 35, (41.4904155617578, 83.5446327449375)),
    ],
)
def test_the_utm_inverse_agrees_with_proj_across_and_beyond_a_zone(easting, northing, zone, proj):
    lat, lon = cog.utm_inverse(easting, northing, zone)
    assert abs(lon - proj[0]) <= 1e-8 and abs(lat - proj[1]) <= 1e-8, (lon, lat)


# ================================================================== the Event: a sensed band


def test_the_ecostress_shaped_band_is_one_observation_event_with_its_values_inline():
    (event,) = _translate(_payload("ecostress_shaped_lst_tiled"))
    identity = (
        "EPSG:32635 8x8 at 320000.0,6340560.0 cell 70.0x70.0 Float32 sensed "
        "2026-04-29T04:17:20.000Z to 2026-04-29T04:18:12.000Z"
    )
    assert event["event_id"] == _uuid("event", "COG", identity)
    assert event["source_ids"] == [{"system": "COG", "external_id": identity}]
    assert (event["event_type"], event["severity"], event["related_entities"]) == (
        "ENVIRONMENTAL_OBSERVATION",
        "INFO",
        [],
    )
    assert (event["observed_at"], event["received_at"]) == ("2026-04-29T04:18:12.000Z", FROZEN)
    assert event["validity"] == {
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
        "effective": {"start": "2026-04-29T04:17:20.000Z", "end": "2026-04-29T04:18:12.000Z"},
    }
    assert event["source"]["observed_at"] == "2026-04-29T04:17:20.000Z"
    assert event["source"]["transformations"] == [
        cog.T_FOOTPRINT_UTM,
        cog.T_WINDOW,
        cog.T_SENSING_RANGE,
    ]
    observation = _observation(event)
    assert observation == {
        "contract": "imagery-product/1",
        "product_class": "observation",
        "product_version": {
            "run": None,
            "version": None,
            "production_time_verbatim": "2026-04-29T11:02:33.000000Z",
            "producer": None,
        },
        "time": {
            "source_time_system": {
                "name": "UTC",
                "stated_by": "source",
                "basis": "GDAL_METADATA (TIFF tag 42112) items RangeBeginningDate, "
                "RangeBeginningTime, RangeEndingDate and RangeEndingTime, each time ending Z",
            },
            "reference_time": None,
            "reference_time_significance": None,
            "forecast_offset": None,
            "statistical_process": None,
        },
        "locator": {
            "kind": "raster",
            "frame_sha256": None,
            "granule_id": None,
            "band_file": None,
            "ifd": 0,
            "tile": 0,
            "window": {"column": 0, "row": 0, "width": 8, "height": 8},
        },
        "quality_flags": [],
        "quality_flags_basis": "the file states no quality summary; a product's quality layers "
        "(HLS Fmask, ECOSTRESS QC) are band files of their own, each its own object",
        "product": {
            "name": None,
            "code": "IFD 0",
            "namespace": "TIFF 6.0: the file's first image file directory, named by its "
            "ImageDescription (tag 270) where it states one",
        },
        "band": {
            "name": "LST",
            "code": "sample 0",
            "namespace": "GDAL_METADATA (TIFF tag 42112) item DESCRIPTION of band 1, where stated",
        },
        "wavelength": None,
        "unit": {
            "unit": "K",
            "unit_namespace": "GDAL_METADATA (TIFF tag 42112) item UNITTYPE, band 1",
        },
        "grid": {
            "namespace": "OGC GeoTIFF 1.1",
            "template": "ProjectedCRSGeoKey 32635",
            "shape": [8, 8],
            "scanning_mode": None,
            "cell_size": [
                {
                    "value": 70.0,
                    "unit": "metre",
                    "unit_namespace": "OGC GeoTIFF 1.1 ModelPixelScaleTag",
                },
                {
                    "value": 70.0,
                    "unit": "metre",
                    "unit_namespace": "OGC GeoTIFF 1.1 ModelPixelScaleTag",
                },
            ],
            "parameters": {
                "geokeys": {
                    "GTModelTypeGeoKey": 1,
                    "GTRasterTypeGeoKey": 1,
                    "GTCitationGeoKey": "WGS 84 / UTM zone 35N",
                    "GeodeticCitationGeoKey": "WGS 84",
                    "GeogAngularUnitsGeoKey": 9102,
                    "ProjectedCRSGeoKey": 32635,
                    "ProjLinearUnitsGeoKey": 9001,
                },
                "ModelPixelScaleTag": [70.0, 70.0, 0.0],
                "ModelTiepointTag": [0.0, 0.0, 0.0, 320000.0, 6340560.0, 0.0],
            },
        },
        "values": {
            "mode": "inline",
            "shape": [8, 8],
            "values": [
                None if (r, c) == (2, 3) else 280 + 0.25 * r + 0.5 * c
                for r in range(8)
                for c in range(8)
            ],
            "missing_mechanism": "GDAL_NODATA (TIFF tag 42113): nan",
        },
    }


def test_the_hls_shaped_band_carries_its_window_by_reference_with_scale_flags_and_clock():
    (event,) = _translate(_payload("hls_shaped_band_cog"))
    assert (event["observed_at"], event["validity"]["effective"]) == (
        "2026-04-29T05:41:07.250Z",
        {"start": "2026-04-29T05:41:07.250Z", "end": "2026-04-29T05:41:07.250Z"},
    )
    observation = _observation(event)
    assert observation["time"]["source_time_system"] == {
        "name": "UTC",
        "stated_by": "source",
        "basis": "GDAL_METADATA (TIFF tag 42112) item SENSING_TIME, an RFC 3339 instant with "
        "its zone",
    }
    # A processing clock, verbatim, and in no key ending _at.
    assert observation["product_version"]["production_time_verbatim"] == "2026-04-30T02:11:45Z"
    assert observation["values"] == {
        "mode": "reference",
        "locator": {
            "kind": "raster",
            "frame_sha256": None,
            "granule_id": None,
            "band_file": None,
            "ifd": 0,
            "tile": 0,
            "window": {"column": 0, "row": 0, "width": 128, "height": 128},
        },
        "shape": [128, 128],
        "dtype": "Int16",
        "encoding": "TIFF Compression 8 (Deflate), Predictor 2 (horizontal differencing)",
        "scale": 0.0001,
        "offset": 0.0,
        "fill": "-9999",
        "summary": {"count": 16384, "missing_count": 5, "min": 1003.0, "max": 1635.0},
    }
    assert observation["unit"] is None and observation["band"]["name"] == "Red"
    flags = [(f["name"], f["value"], f["applies_to"]) for f in observation["quality_flags"]]
    assert flags == [("CLOUD_COVERAGE", "17", "granule"), ("SPATIAL_COVERAGE", "100", "granule")]
    stamps = [k for k in json.dumps(observation).split('"') if k.endswith("_at")]
    assert stamps == []


# ================================================================== the PlanObject: a DEM, a VRT


def test_a_dem_is_one_annotation_with_its_datum_beside_it_and_no_height():
    (plan,) = _translate(_payload("navd88_dem_deflate"))
    identity = "EPSG:4269 4x3 at 23.0,57.4375 cell 0.0625x0.0625 Float32"
    assert (plan["object_kind"], plan["object_type"], plan["label"], plan["validity"]) == (
        "plan_object",
        "ANNOTATION",
        None,
        None,
    )
    assert plan["object_id"] == _uuid("plan_object", "COG", identity)
    assert plan["source_ids"] == [{"system": "COG", "external_id": identity}]
    assert plan["source"]["observed_at"] is None
    assert plan["source"]["transformations"] == [cog.T_FOOTPRINT_NAD83, cog.T_WINDOW]
    assert plan["residual"]["data"]["vertical"] == {
        "datum": {
            "name": "NAVD88 height",
            "namespace": "EPSG:5703, read from OGC GeoTIFF 1.1 VerticalGeoKey (4096)",
        },
        "unit": "metre",
        "unit_namespace": "the axis unit of EPSG:5703 in PROJ's EPSG database",
        "orthometric": True,
    }
    assert "alt_m" not in json.dumps(plan)
    assert plan["residual"]["data"]["ifds"][0]["tags"]["ImageDescription"] == {
        "type": "ASCII",
        "value": "synthetic topography-bathymetry; NAVD88",
    }


def test_an_as_of_lands_at_validity_observed_at_with_its_basis():
    as_of = InjectedTime("2026-04-01T00:00:00Z", "the product's publication date, its catalogue")
    (plan,) = _translate(_payload("float32_lzw_predictor3"), as_of=as_of)
    assert plan["validity"]["observed_at"] == "2026-04-01T00:00:00.000Z"
    assert plan["source"]["observed_at"] == "2026-04-01T00:00:00.000Z"
    assert plan["source"]["transformations"][-1] == (
        "validity.observed_at: the caller's as-of, which the file does not state — the "
        "product's publication date, its catalogue"
    )


def test_a_vrt_index_lists_its_sources_and_opens_none():
    (plan,) = _translate(_payload("local_sources_index"))
    sources = plan["residual"]["data"]["vrt"]["bands"][0]["sources"]
    assert [
        (s["source_filename"], s["relative_to_vrt"], s["DstRect"]["xOff"]) for s in sources
    ] == [
        ("float32_lzw_predictor3.tif", True, "0"),
        ("east/float32_east_half.tif", True, "3"),
    ]
    identity = "VRT EPSG:4326 6x3 at 21.0,57.75 cell 0.25x0.25 2 sources"
    assert plan["object_id"] == _uuid("plan_object", "COG", identity)
    assert cog.vrt_system(plan["residual"]["data"]["vrt"]["srs"]) == (4326, None)
    (compound,) = _translate(_payload("compound_navd88_index"))
    assert cog.vrt_system(compound["residual"]["data"]["vrt"]["srs"]) == (4269, 5703)


def test_band_file_and_granule_id_name_the_object_and_its_locator_and_nothing_else():
    (event,) = _translate(
        _payload("hls_shaped_band_cog"), band_file="band_04.tif", granule_id="granule-0001"
    )
    assert event["source_ids"] == [{"system": "COG", "external_id": "granule-0001/band_04.tif"}]
    assert event["event_id"] == _uuid("event", "COG", "granule-0001/band_04.tif")
    assert event["source"]["original_id"] == "band_04.tif"
    locator = _observation(event)["locator"]
    assert (locator["band_file"], locator["granule_id"]) == ("band_04.tif", "granule-0001")
    for bad in ("dir/band.tif", "", "  ", "x" * 1025):
        with pytest.raises(ValueError):
            CogAdapter(band_file=bad)


def test_two_band_files_of_one_grid_and_time_share_an_id_unless_the_caller_names_them():
    # Two bands of one granule: one grid, one sensing instant, different values and DESCRIPTION.
    def band(name, values):
        return _timed(
            ("SENSING_TIME", "2026-04-29T05:41:07Z"),
            (
                "DESCRIPTION",
                name,
                {"sample": "0", "role": "description"},
            ),
            values=values,
        )

    b02, b03 = band("B02", (1.0, 2.0, 3.0, 4.0)), band("B03", (5.0, 6.0, 7.0, 8.0))
    descriptor = (
        "EPSG:4326 2x2 at 21.0,57.5 cell 0.25x0.25 Float32 sensed "
        "2026-04-29T05:41:07.000Z to 2026-04-29T05:41:07.000Z"
    )
    # With neither band_file nor source_hash the id is what the file states, and the two
    # collide: the documented behaviour (limitation `identity-from-what-the-file-states`).
    (a,), (b,) = _translate(b02), _translate(b03)
    assert a["source_ids"] == b["source_ids"] == [{"system": "COG", "external_id": descriptor}]
    assert a["event_id"] == b["event_id"] == _uuid("event", "COG", descriptor)
    # With the caller's digest of each file, the digest is part of the descriptor.
    hashes = ["0" * 63 + "2", "0" * 63 + "3"]
    (a,), (b,) = (
        _translate(octets, source_hash={"algorithm": "sha256", "value": digest})
        for octets, digest in zip((b02, b03), hashes)
    )
    for event, digest in ((a, hashes[0]), (b, hashes[1])):
        identity = f"{descriptor} sha256 {digest}"
        assert event["source_ids"] == [{"system": "COG", "external_id": identity}]
        assert event["event_id"] == _uuid("event", "COG", identity)
    assert a["event_id"] != b["event_id"]
    # band_file, when given, is the identity and the digest is not added to it.
    (named,) = _translate(
        b02, band_file="band_02.tif", source_hash={"algorithm": "sha256", "value": hashes[0]}
    )
    assert named["source_ids"] == [{"system": "COG", "external_id": "band_02.tif"}]


def test_a_vrt_index_s_descriptor_carries_the_caller_s_digest():
    digest = "ab" * 32
    (plan,) = _translate(_vrt(), source_hash={"algorithm": "sha256", "value": digest})
    identity = f"VRT EPSG:4326 6x3 at 21.0,57.75 cell 0.25x0.25 2 sources sha256 {digest}"
    assert plan["source_ids"] == [{"system": "COG", "external_id": identity}]
    assert plan["object_id"] == _uuid("plan_object", "COG", identity)


# ================================================================== time


def _timed(*items, values=(1.0, 2.0, 3.0, 4.0)):
    return _tiff([(42112, "ASCII", _metadata(*items))], values=values)


def test_a_sensing_time_supplied_by_the_caller_makes_a_dem_an_event_stated_by_the_caller():
    sensed = InjectedTime(
        "2026-04-29T03:00:00+02:00", "the scene's acquisition, from its catalogue"
    )
    (event,) = _translate(_payload("float32_lzw_predictor3"), sensing_time=sensed)
    assert event["observed_at"] == "2026-04-29T01:00:00.000Z"
    assert _observation(event)["time"]["source_time_system"] == {
        "name": "UTC",
        "stated_by": "caller",
        "basis": "the scene's acquisition, from its catalogue",
    }
    assert event["source"]["transformations"][-1] == (
        "validity.effective: the caller's sensing_time, which the file does not state — the "
        "scene's acquisition, from its catalogue"
    )
    # A file stating no unit and carrying 9 values: by reference with its summary.
    assert _observation(event)["values"]["summary"] == {
        "count": 9,
        "missing_count": 0,
        "min": 12.5,
        "max": 21.75,
    }


TIME_REFUSALS = [
    (
        [("SENSING_TIME", "2026-04-29T05:41:07")],
        "unreadable-sensing-time",
        "GDAL_METADATA's SENSING_TIME is not one RFC 3339 instant with seconds and its zone; a "
        "stamp without a zone is never read as UTC",
    ),
    (
        [("SENSING_TIME", "2026-04-29T05:41:07Z; 2026-04-29T05:41:09Z")],
        "unreadable-sensing-time",
        "GDAL_METADATA's SENSING_TIME is not one RFC 3339 instant with seconds and its zone; a "
        "stamp without a zone is never read as UTC",
    ),
    (
        [("SENSING_TIME", "2026-02-30T05:41:07Z")],
        "unreadable-sensing-time",
        "GDAL_METADATA's SENSING_TIME names no instant in UTC",
    ),
    (
        [("SENSING_TIME", "2026-04-29T05:41:07Z"), ("RangeBeginningDate", "2026-04-29")],
        "two-sensing-statements",
        "GDAL_METADATA states both SENSING_TIME and a RangeBeginning/RangeEnding interval",
    ),
    (
        [("RangeBeginningDate", "2026-04-29"), ("RangeBeginningTime", "04:17:20Z")],
        "partial-sensing-range",
        "GDAL_METADATA states some of RangeBeginningDate, RangeBeginningTime, RangeEndingDate "
        "and RangeEndingTime and not all four",
    ),
    (
        [
            ("RangeBeginningDate", "2026-04-29"),
            ("RangeBeginningTime", "04:17:20.000000"),
            ("RangeEndingDate", "2026-04-29"),
            ("RangeEndingTime", "04:18:12.000000Z"),
        ],
        "unreadable-sensing-range",
        "GDAL_METADATA's RangeBeginningDate and RangeBeginningTime are not YYYY-MM-DD and "
        "HH:MM:SS ending Z; a time without its zone is never read as UTC",
    ),
    (
        [
            ("RangeBeginningDate", "2026-04-29"),
            ("RangeBeginningTime", "04:18:12Z"),
            ("RangeEndingDate", "2026-04-29"),
            ("RangeEndingTime", "04:17:20Z"),
        ],
        "sensing-range-reversed",
        "GDAL_METADATA's sensing interval ends before it begins",
    ),
    (
        [("HLS_PROCESSING_TIME", "2026-04-30T02:11:45Z")],
        "sensing-time-required",
        "the file names a sensed product's processing clock and states no sensing time; the "
        "caller supplies it as sensing_time with its basis (DECISIONS L-12), and it is never "
        "taken from the file name or guessed",
    ),
    (
        [("ProductionDateTime", "2026-04-29T11:02:33.000000Z")],
        "sensing-time-required",
        "the file names a sensed product's processing clock and states no sensing time; the "
        "caller supplies it as sensing_time with its basis (DECISIONS L-12), and it is never "
        "taken from the file name or guessed",
    ),
]


@pytest.mark.parametrize("items,code,text", TIME_REFUSALS)
def test_each_time_rule_refuses_with_its_code_and_whole_text(items, code, text):
    err = _refusal(_timed(*items))
    assert (err.code, str(err)) == (code, f"{code}: {text}")


def test_a_sensing_time_with_an_offset_is_read_in_utc_and_names_its_offset():
    (event,) = _translate(_timed(("SENSING_TIME", "2026-04-29T07:41:07.5+02:00")))
    assert event["observed_at"] == "2026-04-29T05:41:07.500Z"
    assert _observation(event)["time"]["source_time_system"]["name"] == "UTC+02:00"


def test_a_required_sensing_time_is_taken_from_the_caller_and_never_from_the_name():
    payload = _timed(("HLS_PROCESSING_TIME", "2026-04-30T02:11:45Z"))
    named = CogAdapter(
        clock=times.frozen_clock(), band_file="HLS.S30.X.2026119T054107.v2.0.B04.tif"
    )
    with pytest.raises(CogRefused) as raised:
        named.to_cdm(payload)
    assert raised.value.code == "sensing-time-required"
    sensed = InjectedTime("2026-04-29T05:41:07Z", "the granule's metadata file, SENSING_TIME")
    (event,) = _translate(payload, sensing_time=sensed)
    assert event["observed_at"] == "2026-04-29T05:41:07.000Z"
    assert _observation(event)["product_version"]["production_time_verbatim"] == (
        "2026-04-30T02:11:45Z"
    )


def test_the_caller_s_times_are_refused_where_they_would_contradict_or_have_no_object():
    sensed = InjectedTime("2026-04-29T05:41:07Z", "the granule's metadata file, SENSING_TIME")
    err = _refusal(_payload("hls_shaped_band_cog"), sensing_time=sensed)
    assert str(err) == (
        "sensing-time-stated-twice: the file's metadata states its sensing time and the caller "
        "supplied one too"
    )
    as_of = InjectedTime("2026-04-01T00:00:00Z", "the product's publication date")
    err = _refusal(_payload("hls_shaped_band_cog"), as_of=as_of)
    assert str(err) == (
        "as-of-for-a-sensed-product: the caller supplied an as-of for a file that states its "
        "sensing time"
    )
    err = _refusal(_payload("local_sources_index"), sensing_time=sensed)
    assert (
        str(err) == "sensing-time-for-an-index: the caller supplied a sensing time for a VRT index"
    )
    with pytest.raises(ValueError, match="not both"):
        CogAdapter(sensing_time=sensed, as_of=as_of)
    with pytest.raises(TypeError):
        CogAdapter(sensing_time="2026-04-29T05:41:07Z")


def test_a_tiff_datetime_is_a_processing_clock_and_never_a_time():
    payload = _tiff([(306, "ASCII", "2026:04:01 12:00:00"), (305, "ASCII", "a writer 1.0")])
    sensed = InjectedTime("2026-04-29T05:41:07Z", "the scene's acquisition, from its catalogue")
    (event,) = _translate(payload, sensing_time=sensed)
    assert _observation(event)["product_version"] == {
        "run": None,
        "version": None,
        "production_time_verbatim": "2026:04:01 12:00:00",
        "producer": "a writer 1.0",
    }
    assert event["observed_at"] == "2026-04-29T05:41:07.000Z"


def test_inline_values_need_a_unit_and_no_scale_and_otherwise_go_by_reference():
    unit = (42112, "ASCII", _metadata(("UNITTYPE", "m", {"sample": "0", "role": "unittype"})))
    sensed = InjectedTime("2026-04-29T05:41:07Z", "the scene's acquisition, from its catalogue")
    (event,) = _translate(_tiff([unit]), sensing_time=sensed)
    assert _observation(event)["values"] == {
        "mode": "inline",
        "shape": [2, 2],
        "values": [1.0, 2.0, 3.0, 4.0],
        "missing_mechanism": None,
    }
    scaled = (
        42112,
        "ASCII",
        _metadata(
            ("UNITTYPE", "m", {"sample": "0", "role": "unittype"}),
            ("SCALE", "0.5", {"sample": "0", "role": "scale"}),
        ),
    )
    (event,) = _translate(_tiff([scaled]), sensing_time=sensed)
    values = _observation(event)["values"]
    assert (values["mode"], values["scale"], values["offset"], values["summary"]) == (
        "reference",
        0.5,
        None,
        {"count": 4, "missing_count": 0, "min": 1.0, "max": 4.0},
    )
    bad = (42112, "ASCII", _metadata(("SCALE", "half", {"sample": "0", "role": "scale"})))
    err = _refusal(_tiff([bad]), sensing_time=sensed)
    assert str(err) == "bad-scale: GDAL_METADATA's SCALE for band 1 is not a finite decimal number"


# ================================================================== georeference and structure


GEO_REFUSALS = [
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4258))},
        "unsupported-crs",
        "IFD 0: GeodeticCRSGeoKey names a system outside the closed set (EPSG:4326, EPSG:4269, "
        "the WGS84 UTM zones)",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4326), (2054, 9105))},
        "unsupported-angular-unit",
        "IFD 0: GeogAngularUnitsGeoKey is not degrees",
    ),
    (
        {"geokeys": _geokeys((1024, 1), (1025, 1), (3072, 32634), (3076, 9002))},
        "unsupported-linear-unit",
        "IFD 0: ProjLinearUnitsGeoKey is not metres",
    ),
    (
        {"geokeys": _geokeys((1024, 3), (1025, 1))},
        "unsupported-crs",
        "IFD 0: GTModelTypeGeoKey is not projected (1) or geographic (2)",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (2048, 4326))},
        "no-raster-type",
        "IFD 0: GTRasterTypeGeoKey is not PixelIsArea (1) or PixelIsPoint (2)",
    ),
    ({"drop": (34735,)}, "no-geokeys", "IFD 0 states no GeoKey directory"),
    (
        {"drop": (33550,)},
        "no-georeference",
        "IFD 0 states no ModelPixelScaleTag and ModelTiepointTag pair",
    ),
    (
        {"extra": [(33922, "DOUBLE", [0.0] * 6 + [1.0, 1.0, 0.0, 21.25, 57.25, 0.0])]},
        "multiple-tiepoints",
        "IFD 0: ModelTiepointTag states other than one tiepoint",
    ),
    (
        {"extra": [(33550, "DOUBLE", [0.25, -0.25, 0.0])]},
        "unsupported-orientation",
        "IFD 0: the pixel scale is not positive on both axes",
    ),
    (
        {"extra": [(34264, "DOUBLE", [0.0] * 16)]},
        "model-transformation",
        "IFD 0 states ModelTransformationTag; a rotated or sheared raster is not read",
    ),
    (
        {"extra": [(274, "SHORT", [3])]},
        "unsupported-orientation",
        "IFD 0 states an Orientation other than 1; GeoTIFF's raster space is row 0 at the top",
    ),
    (
        {"extra": [(254, "LONG", [1])]},
        "first-ifd-not-full-resolution",
        "IFD 0 is marked as an overview or a mask; the full-resolution image comes first",
    ),
    (
        {"extra": [(33922, "DOUBLE", [0.0, 0.0, 0.0, 179.75, 57.5, 0.0])]},
        "footprint-out-of-range",
        "the image's outline leaves -180 to 180 degrees of longitude or -90 to 90 of latitude",
    ),
    (
        {
            "geokeys": _geokeys((1024, 1), (1025, 1), (3072, 32634)),
            "extra": [(33922, "DOUBLE", [0.0, 0.0, 0.0, 1000000.0, 6300000.0, 0.0])],
        },
        "footprint-out-of-range",
        "the image's outline leaves the UTM zone's coordinate range",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4326), (4096, 5773))},
        "unsupported-vertical-crs",
        "IFD 0: VerticalGeoKey names a vertical system outside the closed set (EPSG:5703)",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4326), (4096, 5703), (4098, 5100))},
        "unsupported-vertical-crs",
        "IFD 0: VerticalDatumGeoKey disagrees",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4326), (4096, 5703), (4099, 9002))},
        "unsupported-vertical-crs",
        "IFD 0: VerticalUnitsGeoKey is not metres",
    ),
    (
        {"geokeys": _geokeys((1024, 2), (1025, 1), (2048, 4326), (4099, 9001))},
        "unsupported-vertical-crs",
        "IFD 0 states a vertical datum or unit and no VerticalGeoKey",
    ),
]


@pytest.mark.parametrize("change,code,text", GEO_REFUSALS)
def test_each_georeference_rule_refuses_with_its_code_and_whole_text(change, code, text):
    err = _refusal(_tiff(**change))
    assert (err.code, str(err)) == (code, f"{code}: {text}")


#: A UTM coordinate inside the zone's range can still name a point a WGS84 footprint cannot
#: state: past 180 degrees (zones 1 and 60 at their outer edges) or past a pole. Each is refused
#: by name before a Polygon is built; the 2 x 2 strip has cells of 100 m, the VRT is 6 x 3 cells.
#: The pole's northing is 0.9996 x 10 001 965.729 m (the meridian quadrant) = 9 997 964.943 m.
_ANTIMERIDIAN = "the image's outline crosses 180 degrees; a footprint across it is not stated"
_POLE = "the image's outline reaches a pole; a footprint over it is not stated"
UTM_RANGE_REFUSALS = [
    # zone 1 at easting 168 000 m, 43.6 N: about 181.1 W
    (32601, 168000.0, 4830000.0, "footprint-crosses-antimeridian", _ANTIMERIDIAN),
    # zone 60 at easting 832 000 m, 43.6 N: about 181.1 E
    (32660, 832000.0, 4830000.0, "footprint-crosses-antimeridian", _ANTIMERIDIAN),
    # zone 1 at easting 0, just south of the north pole: the west edge swings past 180 W
    (32601, 0.0, 9997000.0, "footprint-crosses-antimeridian", _ANTIMERIDIAN),
    # zone 31 across the north pole (its outline wraps to 183 E)
    (32631, 499700.0, 9998000.0, "footprint-reaches-pole", _POLE),
    # zone 1 wholly past the north pole: every vertex lies inside -180 to 180, yet past the pole
    (32601, 499700.0, 9999800.0, "footprint-reaches-pole", _POLE),
    # zone 31 south, across the south pole (northing 2 035.057 m)
    (32731, 499700.0, 2100.0, "footprint-reaches-pole", _POLE),
]


def _utm_wkt(code: int) -> str:
    return (
        f'PROJCS["WGS 84 / UTM",GEOGCS["WGS 84",AUTHORITY["EPSG","4326"]],'
        f'AUTHORITY["EPSG","{code}"]]'
    )


@pytest.mark.parametrize("code,easting,northing,refusal,text", UTM_RANGE_REFUSALS)
def test_a_utm_tiff_past_180_degrees_or_a_pole_is_refused_by_name(
    code, easting, northing, refusal, text
):
    err = _refusal(
        _tiff(
            geokeys=_geokeys((1024, 1), (1025, 1), (3072, code)),
            extra=[
                (33550, "DOUBLE", [100.0, 100.0, 0.0]),
                (33922, "DOUBLE", [0.0, 0.0, 0.0, easting, northing, 0.0]),
            ],
        )
    )
    assert (err.code, str(err)) == (refusal, f"{refusal}: {text}")


@pytest.mark.parametrize("code,easting,northing,refusal,text", UTM_RANGE_REFUSALS)
def test_a_utm_vrt_past_180_degrees_or_a_pole_is_refused_by_name(
    code, easting, northing, refusal, text
):
    err = _refusal(
        _vrt(
            srs=_utm_wkt(code),
            mapping="1,2",
            geo_transform=[easting, 100.0, 0.0, northing, 0.0, -100.0],
        )
    )
    assert (err.code, str(err)) == (refusal, f"{refusal}: {text}")


def test_a_utm_tiff_just_short_of_the_pole_is_read_with_proj_s_vertices():
    # North edge 9 997 900 m, 64.9 m short of the pole. PROJ (gdaltransform, GDAL 3.13.3,
    # 2026-10-17, EPSG:32631 to EPSG:4326, -output_xy) reads the north-west and north-east
    # corners as below; every latitude stays under 90.
    (plan,) = _translate(
        _tiff(
            geokeys=_geokeys((1024, 1), (1025, 1), (3072, 32631)),
            extra=[
                (33550, "DOUBLE", [100.0, 100.0, 0.0]),
                (33922, "DOUBLE", [0.0, 0.0, 0.0, 499900.0, 9997900.0, 0.0]),
            ],
        )
    )
    ring = plan["geometry"]["coordinates"][0]
    north_east, north_west = ring[4], ring[6]
    for (lon, lat), (plon, plat) in [
        (north_west, (-53.9990885539871, 89.9989320348718)),
        (north_east, (59.9990885539873, 89.9989320348718)),
    ]:
        assert abs(lon - plon) <= 6e-7 and abs(lat - plat) <= 6e-7, (lon, lat)
    assert all(-90.0 < lat < 90.0 and -180.0 <= lon <= 180.0 for lon, lat in ring)


def test_a_navd88_dem_with_its_datum_and_unit_keys_agreeing_is_read():
    keys = _geokeys((1024, 2), (1025, 1), (2048, 4269), (4096, 5703), (4098, 5103), (4099, 9001))
    (plan,) = _translate(_tiff(geokeys=keys))
    assert plan["residual"]["data"]["vertical"]["datum"]["name"] == "NAVD88 height"


METADATA_REFUSALS = [
    ("<Other/>", "bad-gdal-metadata", "IFD 0: GDAL_METADATA is not a GDALMetadata element"),
    (
        "<GDALMetadata><Value>x</Value></GDALMetadata>",
        "bad-gdal-metadata",
        "IFD 0: GDAL_METADATA holds an element other than a named Item",
    ),
    (
        '<GDALMetadata><Item name="A" colour="red">x</Item></GDALMetadata>',
        "bad-gdal-metadata",
        "IFD 0: a GDAL_METADATA Item carries an attribute not read",
    ),
    (
        '<GDALMetadata><Item name="A" sample="1">x</Item></GDALMetadata>',
        "bad-gdal-metadata",
        "IFD 0: a GDAL_METADATA Item names a sample the image lacks",
    ),
    (
        '<GDALMetadata><Item name="A">x</Item><Item name="A">y</Item></GDALMetadata>',
        "repeated-metadata-item",
        "IFD 0: a GDAL_METADATA Item appears twice",
    ),
    (
        '<!DOCTYPE g [<!ENTITY e "x">]><GDALMetadata/>',
        "gdal-metadata-dtd",
        "IFD 0: GDAL_METADATA is refused (dtd)",
    ),
]


@pytest.mark.parametrize("xml,code,text", METADATA_REFUSALS)
def test_each_gdal_metadata_rule_refuses_with_its_code_and_whole_text(xml, code, text):
    err = _refusal(_tiff([(42112, "ASCII", xml)]))
    assert (err.code, str(err)) == (code, f"{code}: {text}")


def test_an_unknown_private_tag_is_kept_by_its_type_in_the_residual():
    (plan,) = _translate(_tiff([(50000, "SHORT", [7, 8]), (33432, "ASCII", "nobody")]))
    tags = plan["residual"]["data"]["ifds"][0]["tags"]
    assert (tags["Tag50000"], tags["Copyright"]) == (
        {"type": "SHORT", "value": [7, 8]},
        {"type": "ASCII", "value": "nobody"},
    )


# ================================================================== VRT


def _vrt(**change) -> bytes:
    spec = copy.deepcopy(BUILDER.VRT_FIXTURES["local_sources_index"])
    override = change.pop("source", None)
    prologue = change.pop("prologue", "")
    spec.update(change)
    return BUILDER.vrt_text(spec, source_override=override, prologue=prologue)


@pytest.mark.parametrize(
    "name,named",
    [
        ("/vsicurl/https://example.invalid/a.tif", "a GDAL /vsicurl/ path"),
        ("/vsis3/bucket/a.tif", "a GDAL virtual file system path"),
        ("s3://bucket/a.tif", "an s3:// locator"),
        ("https://example.invalid/a.tif", "an http(s):// URL"),
        ("dods://example.invalid/a", "a DAP locator"),
        ("[dap4]https://example.invalid/a", "a DAP locator"),
        ("ftp://example.invalid/a.tif", "a URL"),
        ('GTIFF_DIR:1:"/vsicurl/https://example.invalid/a.tif"', "a GDAL /vsicurl/ path"),
    ],
)
def test_a_remote_source_is_refused_by_name_and_never_opened(name, named):
    err = _refusal(_vrt(source=name))
    assert str(err) == (
        f"remote-source: the VRT's band 1 source 0 names {named}; a source is never opened, and "
        "a remote one would make a reader a network client"
    )


VRT_REFUSALS = [
    (
        b"<VRTDataset rasterXSize='1' rasterYSize='1'><VRTDerivedRasterBand/></VRTDataset>",
        "unsupported-vrt-element",
        "the VRT's VRTDataset holds an element this module does not read",
    ),
    (
        _vrt().replace(b"<SourceBand>", b"<KernelFilteredSource/><SourceBand>", 1),
        "unsupported-vrt-element",
        "the VRT's ComplexSource holds an element this module does not read",
    ),
    (
        _vrt().replace(b'band="1">', b'band="1" subClass="VRTDerivedRasterBand">', 1),
        "unsupported-vrt-attribute",
        "the VRT's VRTRasterBand carries an attribute not read",
    ),
    (b"<Other/>", "not-a-vrt", "the XML document's root is not VRTDataset"),
    (b"<VRTDataset", "vrt-malformed", "the VRT is refused by the XML guard (malformed)"),
    (
        _vrt(prologue='<!DOCTYPE VRTDataset SYSTEM "http://example.invalid/vrt.dtd">\n'),
        "vrt-dtd",
        "the VRT is refused by the XML guard (dtd)",
    ),
    (
        _vrt(geo_transform=[21.0, 0.25, 0.1, 57.75, 0.0, -0.25]),
        "model-transformation",
        "the VRT's GeoTransform rotates the raster",
    ),
    (
        _vrt(geo_transform=[21.0, 0.25, 0.0, 57.75, 0.0, 0.25]),
        "unsupported-orientation",
        "the VRT's GeoTransform is not north-up with positive steps",
    ),
    (
        _vrt(srs="EPSG:3857"),
        "unsupported-crs",
        "the VRT's SRS names a system outside the closed set (EPSG:4326, EPSG:4269, EPSG:5498, "
        "the WGS84 UTM zones)",
    ),
    (
        _vrt(srs='GEOGCRS["WGS 84",ID["EPSG",4326]]'),
        "unsupported-crs",
        "the VRT's SRS is not WKT1 GEOGCS, PROJCS or COMPD_CS",
    ),
    (
        _vrt(srs='GEOGCS["WGS 84"'),
        "unsupported-crs",
        "the VRT's SRS is neither EPSG:<code> nor WKT1 this module reads",
    ),
    (
        _vrt(srs='GEOGCS["WGS 84",DATUM["WGS_1984"]]'),
        "unsupported-crs",
        "the VRT's SRS names no single EPSG authority",
    ),
    (
        _vrt(mapping="1,2"),
        "unsupported-axis-mapping",
        "the VRT's dataAxisToSRSAxisMapping is not GDAL's traditional GIS order",
    ),
    (
        _vrt().replace(b"<GeoTransform>", b"<GeoTransform>1, 2, ", 1),
        "bad-vrt",
        "the VRT's GeoTransform is not six numbers",
    ),
    (
        _vrt().replace(b'rasterXSize="6"', b'rasterXSize="0"', 1),
        "bad-vrt",
        "the VRT's VRTDataset rasterXSize is not a positive integer",
    ),
]


@pytest.mark.parametrize("octets,code,text", VRT_REFUSALS)
def test_each_vrt_rule_refuses_with_its_code_and_whole_text(octets, code, text):
    err = _refusal(octets)
    assert (err.code, str(err)) == (code, f"{code}: {text}")


def test_the_short_epsg_form_and_a_utm_wkt_are_read():
    (plan,) = _translate(_vrt(srs="EPSG:4326"))
    assert plan["geometry"]["coordinates"][0][0] == [21.0, 57.0]
    utm = (
        'PROJCS["WGS 84 / UTM zone 34N",GEOGCS["WGS 84",AUTHORITY["EPSG","4326"]],'
        'AUTHORITY["EPSG","32634"]]'
    )
    (plan,) = _translate(
        _vrt(srs=utm, mapping="1,2", geo_transform=[470000.0, 30.0, 0.0, 6320090.0, 0.0, -30.0])
    )
    ring = plan["geometry"]["coordinates"][0]
    assert (
        abs(ring[0][0] - PROJ_UTM_COG[0][0]) <= 6e-7
        and abs(ring[0][1] - PROJ_UTM_COG[0][1]) <= 6e-7
    )


# ================================================================== twins, inputs and bounds


def test_a_twin_must_be_exactly_what_its_wire_hex_decodes_to():
    twin = _twin("float32_lzw_predictor3")
    err = _refusal({**twin, "extra": 1})
    assert err.code == "not-a-twin"
    assert str(err) == (
        "not-a-twin: a dict is the file's twin, exactly: wire_hex, header, ifds, arrays, "
        "geokeys, gdal_metadata, vertical, window; or wire_hex, vrt"
    )
    err = _refusal({**twin, "wire_hex": "ABC"})
    assert str(err) == (
        "bad-wire-hex: wire_hex is not lower-case hexadecimal of at most 268435456 octets"
    )
    changed = copy.deepcopy(twin)
    changed["window"]["max"] = 99.0
    assert str(_refusal(changed)) == (
        "twin-disagrees: the twin's window is not what its wire_hex decodes to"
    )
    vrt_shaped = {"wire_hex": twin["wire_hex"], "vrt": {}}
    assert str(_refusal(vrt_shaped)) == (
        "twin-disagrees: the twin's form is not what its wire_hex decodes to"
    )


def test_text_and_other_types_are_refused_and_so_is_a_payload_neither_tiff_nor_xml():
    err = _refusal(_payload("local_sources_index").decode())
    assert str(err) == (
        "unsupported-input: a file is handed over as its octets or as its twin in a dict; text "
        "and other types are not taken"
    )
    err = _refusal(b"GIF89a")
    assert str(err) == (
        "not-a-tiff-or-vrt: the payload opens neither with a TIFF header nor with XML"
    )


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    deep: dict = {}
    node = deep
    for _ in range(17):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(InputTooDeep):
        CogAdapter(clock=times.frozen_clock()).to_cdm({"wire_hex": "", "header": deep})


def test_the_structure_bounds_are_enforced_before_what_they_bound_is_read():
    # 65 directories chained: the 65th is refused before it is read.
    one = _tiff()
    chain = bytearray(one)
    count = struct.unpack("<H", one[8:10])[0]
    link = 8 + 2 + 12 * count
    tail = len(chain)
    chain[link : link + 4] = struct.pack("<I", tail)
    for k in range(64):
        nxt = tail + 6 if k < 63 else 0
        chain += struct.pack("<H", 1) + struct.pack("<HHI", 256, 3, 1) + b"\x02\x00\x00\x00"
        chain += struct.pack("<I", nxt + 12 if nxt else 0)
        tail = len(chain)
    err = _refusal(bytes(chain))
    assert str(err) == "too-many-ifds: the file chains more than 64 IFDs; refused there"
    # 129 entries in one directory.
    many = _tiff([(40000 + k, "SHORT", [k]) for k in range(129 - len(BUILDER.base_entries()) - 2)])
    assert str(_refusal(many)) == "too-many-entries: IFD 0 states more than 128 entries"
    # One value of more than 1 MiB, and values past 4 MiB together.
    big = _tiff([(40000, "BYTE", [0] * (1024 * 1024 + 1))])
    assert str(_refusal(big)) == (
        "tag-past-its-bound: IFD 0: Tag40000's value is longer than 1048576 octets"
    )
    # Four values of 1 MiB fill the 4 MiB total, and the directory's own GeoTIFF values are
    # counted first, so the fourth crosses it.
    shared = _tiff([(40000 + k, "BYTE", [0] * (1024 * 1024)) for k in range(4)])
    assert str(_refusal(shared)) == (
        "values-past-their-bound: IFD 0: Tag40003 takes the directories' values past their total "
        "bound"
    )
    # A VRT of more than 65 536 elements is refused at the element that crosses the bound.
    sources = b"<Metadata>" + b'<MDI key="k">v</MDI>' * 65536 + b"</Metadata>"
    vrt = _vrt().replace(b"<Metadata>", sources + b"<Metadata>", 1)
    err = _refusal(vrt)
    assert (err.code, str(err)) == (
        "vrt-elements",
        "vrt-elements: the VRT is refused by the XML guard (elements)",
    )


def test_a_block_is_held_to_the_bound_before_and_while_it_inflates():
    # Exactly the bound: one 512 x 512 Float32 tile of zeros, 1 048 576 octets, decodes.
    entries = BUILDER.base_entries(512, 512, compression=8) + [
        (322, "SHORT", [512]),
        (323, "SHORT", [512]),
    ]
    exact = BUILDER.tiff_file(entries, [BUILDER.deflate_zeros(1024 * 1024)], tiled=True)
    window = cog.decode_tiff(exact)["window"]
    assert (window["count"], window["min"], window["max"], window["values"]) == (
        262144,
        0.0,
        0.0,
        None,
    )
    # One octet more in the stream, and a tile whose size alone is past the bound.
    for name in ("tile_inflates_past_its_size.tif", "tile_past_the_decompression_bound.tif"):
        code, text = MALFORMED_TABLE[name]
        assert str(_refusal((MALFORMED / name).read_bytes())) == f"{code}: {text}"
    over = BUILDER.tiff_file(entries, [BUILDER.deflate_zeros(1024 * 1024 + 1)], tiled=True)
    assert _refusal(over).code == "block-inflates-past-its-size"


def test_a_blank_metadata_item_or_text_tag_states_nothing_and_breaks_nothing():
    sensed = InjectedTime("2026-04-29T05:41:07Z", "the scene's acquisition, from its catalogue")
    blank = _tiff(
        [
            (
                42112,
                "ASCII",
                _metadata(
                    ("HLS_PROCESSING_TIME", " "),
                    ("CLOUD_COVERAGE", " "),
                    ("DESCRIPTION", "", {"sample": "0", "role": "description"}),
                ),
            ),
            (270, "ASCII", " "),
            (305, "ASCII", ""),
        ]
    )
    # A blank processing clock does not make the file a sensed product, so it is a PlanObject...
    (plan,) = _translate(blank)
    assert plan["object_kind"] == "plan_object"
    # ...and with a sensing time supplied every blank is read as not stated.
    (event,) = _translate(blank, sensing_time=sensed)
    observation = _observation(event)
    assert (observation["product_version"], observation["quality_flags"]) == (None, [])
    assert (observation["product"]["name"], observation["band"]["name"]) == (None, None)
    assert event["residual"]["data"]["gdal_metadata"][0] == {
        "name": "HLS_PROCESSING_TIME",
        "sample": None,
        "role": None,
        "domain": None,
        "value": " ",
    }


def test_an_integer_sample_s_nodata_is_compared_as_an_integer():
    def int16(nodata, values):
        entries = [(258, "SHORT", [16]), (339, "SHORT", [2]), (42113, "ASCII", nodata)]
        return _tiff(entries, blocks=[struct.pack("<4h", *values)])

    window = cog.decode_tiff(int16("-9999", (-9999, 3, -9999, 4)))["window"]
    assert (window["values"], window["missing_count"]) == ([None, 3, None, 4], 2)
    # A fraction no Int16 can equal marks nothing missing.
    window = cog.decode_tiff(int16("-9999.5", (-9999, 3, -9999, 4)))["window"]
    assert (window["values"], window["missing_count"]) == ([-9999, 3, -9999, 4], 0)
    err = _refusal(int16("1" + "0" * 400, (1, 2, 3, 4)))
    assert str(err) == "bad-nodata: IFD 0: GDAL_NODATA names no number a double holds"
