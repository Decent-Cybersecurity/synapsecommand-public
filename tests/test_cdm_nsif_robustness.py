"""The SC4545-CORE-1 invariants and the vector sweeps the codec module does not already hold:
REQ-086's eleven invariants plus its rule that fuzz input is never evaluated, one test each
(`test_invariant_<n>_<short>`), over the kit's 17 vectors, the 47 native vectors under
`fixtures/stanag4545/vectors/` and every proper prefix of `mono_nsif101.ntf`; REQ-080's
byte-boundary truncation sweep with the code, stage, offset and path of every length; and the
REQ-079 positive cases not held elsewhere (a payload at the input cap retained exactly, more than
one image translated, an image count on every footprint).

Every expectation is a literal or comes from an independent source: the field table of the kit's
`contracts/file-header-fields.json` written out below, the goldens reviewed when they were first
staged, the packaged builder's input planes (the builder only appends samples in each mode's wire
order, so what it was given is the expectation for what it wrote), and corner texts written by
hand. Package-only: every path is anchored on the imported package; nothing is written outside
`tmp_path`; the audit hook of invariant 10 runs in a child interpreter, never in this process.
"""

from __future__ import annotations

import ast
import base64
import importlib.machinery
import json
import pathlib
import subprocess
import sys
import sysconfig
import types

import pytest

import synapse_cdm
from synapse_cdm import canonical, times
from synapse_cdm.adapters import nsif_codec as nc
from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter, Stanag4545Context

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "stanag4545"
ADAPTERS = PACKAGE / "adapters"
LIMITS = nc.CORE1_LIMITS

#: The eleven translatable kit vectors (top level, with twins and goldens).
TOP_LEVEL = (
    "geo_dms",
    "image_and_text",
    "mode_B",
    "mode_P",
    "mode_R",
    "mode_S",
    "mono_nitf210",
    "mono_nsif100",
    "mono_nsif101",
    "uint16",
    "unknown_duplicate_tre",
)
MALFORMED = ("bad_count", "bad_file_length", "trailing", "truncated", "unsupported_stype")

#: The prefix of a file header, from the kit's field contract: (first octet, octets, path).
#: The security block is cut as a whole (a block cut by its structure is one fault).
HEADER_FIELDS = (
    (0, 9, "/file_header/FHDR"),
    (9, 2, "/file_header/CLEVEL"),
    (11, 4, "/file_header/STYPE"),
    (15, 10, "/file_header/OSTAID"),
    (25, 14, "/file_header/FDT"),
    (39, 80, "/file_header/FTITLE"),
    (119, 167, "/file_header/security"),
    (286, 5, "/file_header/FSCOP"),
    (291, 5, "/file_header/FSCPYS"),
    (296, 1, "/file_header/ENCRYP"),
    (297, 3, "/file_header/FBKGC"),
    (300, 24, "/file_header/ONAME"),
    (324, 18, "/file_header/OPHONE"),
    (342, 12, "/file_header/FL"),
)

#: The sixteen fields of a security block: (name, offset in the block, width).
SECURITY_LAYOUT = (
    ("CLAS", 0, 1),
    ("CLSY", 1, 2),
    ("CODE", 3, 11),
    ("CTLH", 14, 2),
    ("REL", 16, 20),
    ("DCTP", 36, 2),
    ("DCDT", 38, 8),
    ("DCXM", 46, 4),
    ("DG", 50, 1),
    ("DGDT", 51, 8),
    ("CLTX", 59, 43),
    ("CAPT", 102, 1),
    ("CAUT", 103, 40),
    ("CRSN", 143, 1),
    ("SRDT", 144, 8),
    ("CTLN", 152, 15),
)

#: geo_dms's IGEOLO (at 776; ICORDS at 775) and hand-written texts for every refusal reason
#: that suppresses a footprint: (ICORDS, IGEOLO, status, reason).
GEO_DMS = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
NO_FOOTPRINT = (
    (
        "G",
        "480000X0170000E480000N0180000E470000N0180000E470000N0170000E",
        "invalid",
        "corner_syntax",
    ),
    (
        "G",
        "486000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        "invalid",
        "corner_range",
    ),
    ("G", "480000N0170000E" * 4, "invalid", "degenerate"),
    (
        "G",
        "480000N0170000E470000N0190000E480000N0190000E460000N0170000E",
        "invalid",
        "self_intersection",
    ),
    (
        "G",
        "900000N0170000E480000N0180000E470000N0180000E470000N0170000E",
        "unsupported",
        "pole_corner",
    ),
    (
        "G",
        "480000N0000000E480000N1800000E470000N1800000E470000N0000000E",
        "unsupported",
        "ambiguous_edge",
    ),
    ("G", "480000N0000000E480000N1000000E470000N1500000W470000N0000000E", "unsupported", "span"),
    ("U", GEO_DMS, "unsupported", "icords_unsupported"),
    ("D", GEO_DMS, "invalid", "corner_syntax"),
)

#: The context under which header_only translates (it has no image identifier to key on).
HEADER_ONLY_CONTEXT = Stanag4545Context(product_key="robustness-header-only")


def _builder():
    """The packaged builder, loaded from SOURCE, as the codec module loads it."""
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("stanag4545_build_fixtures_robustness")
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


BUILDER = _builder()


def kit(stem: str) -> bytes:
    if stem in MALFORMED:
        return (FIXTURES / "malformed" / f"{stem}.ntf").read_bytes()
    if stem == "header_only":
        return (FIXTURES / "context" / "header_only.ntf").read_bytes()
    return (FIXTURES / f"{stem}.ntf").read_bytes()


NATIVE = {path.stem: path.read_bytes() for path in sorted((FIXTURES / "vectors").glob("*.ntf"))}
MONO = kit("mono_nsif101")
#: Every accepted vector: the twelve kit ones and the 47 native ones.
ACCEPTED = {**{stem: kit(stem) for stem in (*TOP_LEVEL, "header_only")}, **NATIVE}
#: Every refused input: the kit's five negatives and every proper prefix of mono_nsif101.
REFUSED = {
    **{stem: kit(stem) for stem in MALFORMED},
    **{f"mono_nsif101[:{end}]": MONO[:end] for end in range(len(MONO))},
}


def adapter_for(stem: str) -> Stanag4545Adapter:
    context = HEADER_ONLY_CONTEXT if stem == "header_only" else None
    return Stanag4545Adapter(clock=times.frozen_clock(), context=context)


def dump(objects) -> list[dict]:
    return [item.model_dump(mode="json") for item in objects]


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def slices(value, found: list) -> list:
    """Every Slice reachable from a parse record."""
    if isinstance(value, nc.Slice):
        found.append(value)
    elif hasattr(value, "__dataclass_fields__") and not isinstance(value, type):
        for name in value.__dataclass_fields__:
            slices(getattr(value, name), found)
    elif isinstance(value, (tuple, list)):
        for item in value:
            slices(item, found)
    elif isinstance(value, types.MappingProxyType) or isinstance(value, dict):
        for item in value.values():
            slices(item, found)
    return found


def native_planes() -> dict[str, list]:
    """The builder's input planes for each native vector, by stem: what it laid out, so what a
    storage window must read back (each vector's bands, rows and columns of samples, from the
    sample formula its name states)."""
    b = BUILDER
    out = {}
    literal = b.planes(2, 4, 5, b.literal_sample)
    one = b.planes(1, 3, 5, b.sample8)
    for mode in "bprs":
        out[f"native_lit_{mode}"] = literal
        out[f"native_edge8_{mode}"] = b.planes(3, 5, 7, b.sample8)
        out[f"native_edge16_{mode}"] = b.planes(3, 5, 7, b.sample16)
        for prefix, count in (("nbands9", 9), ("xbands10", 10), ("xbands256", 256)):
            out[f"native_{prefix}_{mode}"] = b.planes(count, 3, 5, b.sample8)
    for stem in ("nppb_zero", "nppbh_zero_only", "one_block_padded"):
        out[f"native_{stem}"] = one
    for label, _, _, _, _, values in b.INTERPRETATION:
        out[f"native_{label}"] = [[list(values[:3]), list(values[3:])]]
    out["native_lut3"] = [[[0, 1], [2, 3]]]
    for label, _, _ in b.RECTANGLES:
        out[f"native_{label}"] = one
    return out


def window_grid(image) -> list[tuple[int, int, int, int]]:
    """Windows over an image at the block edges and the raster edges: single samples, the rest
    of the raster, and one block's worth, so every edge block is visited."""
    xs = sorted({0, 1, image.block_width - 1, image.block_width, image.ncols - 1})
    ys = sorted({0, 1, image.block_height - 1, image.block_height, image.nrows - 1})
    windows = set()
    for x in (value for value in xs if 0 <= value < image.ncols):
        for y in (value for value in ys if 0 <= value < image.nrows):
            windows.add((x, y, 1, 1))
            windows.add((x, y, image.ncols - x, image.nrows - y))
            width = min(image.block_width, image.ncols - x)
            height = min(image.block_height, image.nrows - y)
            windows.add((x, y, width, height))
    return sorted(windows)


def band_choice(count: int) -> tuple[int, ...]:
    return tuple(reversed(range(count))) if count <= 3 else (count - 1, 0, count // 2)


def with_fl(raw: bytes, value: int) -> bytes:
    return raw[:342] + str(value).zfill(12).encode("ascii") + raw[354:]


def with_igeolo(raw: bytes, icords: str, text: str) -> bytes:
    return raw[:775] + icords.encode("ascii") + text.encode("ascii") + raw[836:]


# =========================================================================== REQ-080's truncations


def test_every_truncation_of_mono_nsif101_is_refused_at_the_field_it_cuts():
    """A file cut at octet n is refused at the first header field that does not fit; from FL on,
    FL itself no longer equals the input length (847)."""
    assert len(MONO) == 847
    assert sum(width for _, width, _ in HEADER_FIELDS) == 354
    for end in range(len(MONO)):
        offset, path = next(
            (start, path)
            for start, width, path in HEADER_FIELDS
            if end < start + width or path == "/file_header/FL"
        )
        with pytest.raises(nc.NsifError) as caught:
            nc.parse_container(MONO[:end], LIMITS)
        error = caught.value
        assert (error.code, error.stage, error.offset, error.path) == (
            "E_LENGTH",
            "header",
            offset,
            path,
        ), end
    # Spot values written out: the empty file, the last octet of the magic, inside the security
    # block, the last octet before FL, the first octet of the directory, one octet short.
    for end, offset, path in (
        (0, 0, "/file_header/FHDR"),
        (8, 0, "/file_header/FHDR"),
        (9, 9, "/file_header/CLEVEL"),
        (200, 119, "/file_header/security"),
        (341, 324, "/file_header/OPHONE"),
        (353, 342, "/file_header/FL"),
        (360, 342, "/file_header/FL"),
        (846, 342, "/file_header/FL"),
    ):
        with pytest.raises(nc.NsifError) as caught:
            nc.parse_container(MONO[:end], LIMITS)
        assert (caught.value.offset, caught.value.path) == (offset, path), end


def test_every_truncation_is_refused_by_to_cdm_and_validate_source_alike():
    instance = Stanag4545Adapter(clock=times.frozen_clock())
    for end in (0, 8, 9, 119, 285, 342, 354, 404, 842, 846):
        expected = "E_LENGTH @byte {} {}: ".format(
            *next(
                (start, path)
                for start, width, path in HEADER_FIELDS
                if end < start + width or path == "/file_header/FL"
            )
        )
        with pytest.raises(nc.NsifError) as caught:
            instance.to_cdm(MONO[:end])
        assert str(caught.value).startswith(expected), end
        found = instance.validate_source(MONO[:end])
        assert len(found) == 1 and found[0].startswith(expected), end


# =========================================================================== REQ-079's cases


def test_a_payload_at_the_input_cap_is_retained_exactly():
    """REQ-079 "large raw payload retention": a 16,777,216-octet container (one mono 8-bit image
    of 19 x 882,967 samples in one block) translates, and its octets come back from wire_b64."""
    rows, columns = 19, 882_967
    data = (bytes(range(251)) * (rows * columns // 251 + 1))[: rows * columns]
    header = bytearray(MONO[:843])
    for offset, width, value in (
        (342, 12, 843 + len(data)),  # FL
        (369, 10, len(data)),  # LI
        (737, 8, rows),  # NROWS
        (745, 8, columns),  # NCOLS
        (803, 4, 0),  # NPPBH: one block across
        (807, 4, 0),  # NPPBV: one block down
    ):
        header[offset : offset + width] = str(value).zfill(width).encode("ascii")
    raw = bytes(header) + data
    assert len(raw) == LIMITS.input_bytes == 16_777_216
    objects = Stanag4545Adapter(clock=times.frozen_clock()).to_cdm(raw)
    assert len(objects) == 1
    wire = objects[0].residual.data["stanag4545"]["wire_b64"]
    assert base64.b64decode(wire, validate=True) == raw
    image = objects[0].attributes["stanag4545"]["images"][0]
    assert (image["pixel_status"], image["geometry_status"]) == ("native_supported", "absent")


def test_more_than_one_image_translates_with_its_own_footprint_and_count():
    """REQ-079 "one and multiple images": two copies of geo_dms's image, the second with
    corners one degree further east, give a product and two footprints, in image order, each
    naming its image and the count."""
    found = nc.parse_container(kit("geo_dms"), LIMITS)
    segment = found.images[0].segment
    raw = found.raw
    subheader = raw[segment.subheader.offset : segment.subheader.offset + segment.subheader.length]
    pixels = raw[segment.data.offset : segment.data.offset + segment.data.length]
    east = "480000N0180000E480000N0190000E470000N0190000E470000N0180000E"
    second = subheader[: 776 - 404] + east.encode("ascii") + subheader[776 - 404 + 60 :]
    built = BUILDER.container([(subheader, pixels), (second, pixels)])
    objects = Stanag4545Adapter(clock=times.frozen_clock()).to_cdm(built)
    assert [type(item).__name__ for item in objects] == ["Entity", "PlanObject", "PlanObject"]
    records = [item.residual.data["stanag4545"] for item in objects[1:]]
    assert [record["image"]["index"] for record in records] == [0, 1]
    assert [record["product"]["image_count"] for record in records] == [2, 2]
    rings = [item["geometry"]["coordinates"][0] for item in dump(objects[1:])]
    assert rings[0][0] == [17.0, 48.0] and rings[1][0] == [18.0, 48.0]
    assert len(objects[0].attributes["stanag4545"]["images"]) == 2


# =========================================================================== REQ-086's invariants


def test_invariant_1_no_read_outside_input():
    """Every slice a returned container records lies inside the input, the container keeps the
    caller's object itself, and every numeric field it reports is the decimal its slice holds;
    every refusal names an offset inside the input."""
    numeric = ("NROWS", "NCOLS", "ABPP", "NBPR", "NBPC", "NBPP")
    for stem, raw in ACCEPTED.items():
        found = nc.parse_container(raw, LIMITS)
        assert found.raw is raw, stem
        for part in slices(found, []):
            assert 0 <= part.offset and part.offset + part.length <= len(raw), (stem, part)
        for image in found.images:
            for name, value in zip(
                numeric,
                (image.nrows, image.ncols, image.abpp, image.nbpr, image.nbpc, image.nbpp),
            ):
                part = image.fields[name]
                assert int(raw[part.offset : part.offset + part.length]) == value, (stem, name)
        for record in (found.file_header, *found.images, *found.texts, *found.des, *found.res):
            for name, part in record.fields.items():
                text, status = nc.ascii_text(raw, part)
                octets = raw[part.offset : part.offset + part.length]
                if status == "printable_ascii":
                    assert text == octets.decode("ascii").rstrip(" "), (stem, name)
    for stem, raw in REFUSED.items():
        with pytest.raises(nc.NsifError) as caught:
            nc.parse_container(raw, LIMITS)
        assert caught.value.offset is None or 0 <= caught.value.offset <= len(raw), stem


def test_invariant_2_no_write_outside_a_window():
    """Every window of a grid over each native image, edge blocks included, holds exactly its
    width x height x bands samples, each the one the builder laid out there: no pad sample and
    nothing from outside the window. Kit images: every sub-window equals the same slice of the
    whole window."""
    planes = native_planes()
    assert sorted(planes) == sorted(NATIVE)
    for stem, raw in NATIVE.items():
        found = nc.parse_container(raw, LIMITS)
        image = found.images[0]
        expected = planes[stem]
        bands = band_choice(image.band_count)
        for x, y, width, height in window_grid(image):
            window = nc.decode_nc_window(found, 0, x, y, width, height, bands, storage=True)
            assert window.values() == tuple(
                expected[band][row][column]
                for band in bands
                for row in range(y, y + height)
                for column in range(x, x + width)
            ), (stem, x, y, width, height)
    for stem in TOP_LEVEL:
        found = nc.parse_container(kit(stem), LIMITS)
        for index, image in enumerate(found.images):
            bands = tuple(range(image.band_count))
            whole = nc.decode_nc_window(found, index, 0, 0, image.ncols, image.nrows, bands)
            values = whole.values()
            for x, y, width, height in window_grid(image):
                part = nc.decode_nc_window(found, index, x, y, width, height, bands)
                assert len(part.values()) == width * height * len(bands)
                assert part.values() == tuple(
                    values[(band * image.nrows + row) * image.ncols + column]
                    for band in bands
                    for row in range(y, y + height)
                    for column in range(x, x + width)
                ), (stem, x, y, width, height)


def test_invariant_3_segment_sum_equals_fl():
    """Every accepted vector's header and segments add up to FL, which is the input length; FL
    one more or one less is refused at FL."""
    for stem, raw in ACCEPTED.items():
        found = nc.parse_container(raw, LIMITS)
        total = found.header_length + sum(
            segment.subheader.length + segment.data.length for segment in found.segments
        )
        assert total == found.file_size == len(raw) == int(raw[342:354]), stem
        for delta in (-1, 1):
            with pytest.raises(nc.NsifError) as caught:
                nc.parse_container(with_fl(raw, len(raw) + delta), LIMITS)
            error = caught.value
            assert (error.code, error.stage, error.offset, error.path) == (
                "E_LENGTH",
                "header",
                342,
                "/file_header/FL",
            ), (stem, delta)


def test_invariant_4_exact_byte_retention():
    """The product's wire_b64 decodes to the input, from the container and from its twin."""
    for stem, raw in ACCEPTED.items():
        envelope = {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(raw).decode("ascii")}
        for given in (raw, envelope):
            objects = adapter_for(stem).to_cdm(given)
            wire = objects[0].residual.data["stanag4545"]["wire_b64"]
            assert base64.b64decode(wire, validate=True) == raw, stem
    for stem in TOP_LEVEL:
        packaged = json.loads((FIXTURES / f"{stem}.parsed.json").read_text(encoding="utf-8"))
        objects = adapter_for(stem).to_cdm(packaged)
        assert base64.b64decode(objects[0].residual.data["stanag4545"]["wire_b64"]) == kit(stem)


def test_invariant_5_deterministic_output_for_a_fixed_context():
    """Two fresh adapters with the frozen clock give byte-identical canonical JSON, equal to the
    reviewed golden, from the container and from its twin."""
    for stem in TOP_LEVEL:
        twin = json.loads((FIXTURES / f"{stem}.parsed.json").read_text(encoding="utf-8"))
        for given, golden in ((kit(stem), f"{stem}.cdm.json"), (twin, f"{stem}.parsed.cdm.json")):
            first = canonical.serialise(dump(adapter_for(stem).to_cdm(given)))
            second = canonical.serialise(dump(adapter_for(stem).to_cdm(given)))
            assert first == second, stem
            assert first == (FIXTURES / "golden" / golden).read_text(encoding="utf-8"), golden
    first = canonical.serialise(dump(adapter_for("header_only").to_cdm(kit("header_only"))))
    assert first == canonical.serialise(dump(adapter_for("header_only").to_cdm(kit("header_only"))))


def test_invariant_6_raw_bytes_attached_once():
    """The whole input's base64 occurs exactly once in the serialised output, and no other string
    of 88 or more characters decodes as strict base64 to octets of the input."""
    for stem, raw in ACCEPTED.items():
        dumped = dump(adapter_for(stem).to_cdm(raw))
        text = canonical.serialise(dumped)
        whole = base64.b64encode(raw).decode("ascii")
        assert text.count(whole) == 1, stem
        for value in strings(dumped):
            if value == whole or len(value) < 88:
                continue
            try:
                decoded = base64.b64decode(value, validate=True)
            except ValueError:
                continue
            assert decoded not in raw, (stem, value[:40])


def test_invariant_7_no_published_object_from_malformed_input():
    """Every refused input raises a coded error from to_cdm and returns nothing, as a container
    and as a twin, and validate_source answers one string."""
    instance = Stanag4545Adapter(clock=times.frozen_clock())
    for stem, raw in REFUSED.items():
        envelope = {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(raw).decode("ascii")}
        for given in (raw, envelope):
            returned = None
            with pytest.raises(nc.NsifError):
                returned = instance.to_cdm(given)
            assert returned is None, stem
        assert len(instance.validate_source(raw)) == 1, stem
    for stem, raw in ACCEPTED.items():
        for delta in (-1, 1):
            with pytest.raises(nc.NsifError):
                instance.to_cdm(with_fl(raw, len(raw) + delta))


def test_invariant_8_no_footprint_when_coordinate_interpretation_fails():
    """geo_dms with corners that no footprint can come from gives the product alone: no
    PlanObject, the image's geometry status and reason recorded, its pixels still native."""
    instance = Stanag4545Adapter(clock=times.frozen_clock())
    assert len(instance.to_cdm(kit("geo_dms"))) == 2
    for icords, text, status, reason in NO_FOOTPRINT:
        raw = with_igeolo(kit("geo_dms"), icords, text)
        objects = instance.to_cdm(raw)
        assert [type(item).__name__ for item in objects] == ["Entity"], (icords, text)
        image = objects[0].attributes["stanag4545"]["images"][0]
        assert (image["geometry_status"], image["pixel_status"]) == (status, "native_supported")
        found = nc.parse_container(raw, LIMITS).images[0]
        assert (found.geometry_status, found.geometry_reason) == (status, reason), text


def test_invariant_9_no_source_security_loss():
    """Every field of every security block, read here from the block's own octets with the
    sixteen widths above, is on the product's labels and on each footprint's (the file label and
    its own image's), trimmed of trailing spaces, or null and named uninterpreted."""
    for stem, raw in ACCEPTED.items():
        found = nc.parse_container(raw, LIMITS)
        blocks = [("file", None, found.file_header.security)]
        for kind, records in (
            ("image", found.images),
            ("graphic", found.graphics),
            ("text", found.texts),
            ("des", found.des),
            ("res", found.res),
        ):
            blocks += [(kind, record.index, record.security) for record in records]
        expected = []
        for scope, index, block in blocks:
            start = block.slice.offset
            assert block.slice.length == 167
            fields, uninterpreted = {}, []
            for name, at, width in SECURITY_LAYOUT:
                octets = raw[start + at : start + at + width]
                if all(0x20 <= octet <= 0x7E for octet in octets):
                    fields[name] = octets.decode("ascii").rstrip(" ")
                else:
                    fields[name] = None
                    uninterpreted.append(name)
            expected.append(
                {
                    "scope": scope,
                    "index": index,
                    "offset": start,
                    "length": 167,
                    "fields": fields,
                    "uninterpreted": uninterpreted,
                }
            )
        objects = dump(adapter_for(stem).to_cdm(raw))
        assert objects[0]["residual"]["data"]["stanag4545"]["security"]["labels"] == expected
        for footprint in objects[1:]:
            record = footprint["residual"]["data"]["stanag4545"]
            own = record["image"]["index"]
            assert record["security"]["labels"] == [
                expected[0],
                next(
                    label
                    for label in expected
                    if label["scope"] == "image" and label["index"] == own
                ),
            ], stem


#: Invariant 10's child: the package and the standard library first, then the hook, then the three
#: adapter modules, one warm-up round of calls, the measured round, and the record on stdout.
PROGRAM = r"""
import json
import pathlib
import sys

import synapse_cdm

package = pathlib.Path(synapse_cdm.__file__).resolve().parent
root = package / "fixtures" / "stanag4545"
vectors = [path.read_bytes() for path in sorted(root.rglob("*.ntf")) if path.parent.name != "vectors"]
phase = ["imports"]
events = []
WATCHED = ("socket.", "subprocess.", "urllib.", "http.", "ftplib.", "os.exec", "os.spawn")
NAMED = {"open", "os.system", "os.posix_spawn", "os.remove", "os.rename", "os.mkdir", "os.rmdir"}


def hook(event, args):
    if event in NAMED or event.startswith(WATCHED):
        detail = [str(args[0]), str(args[1])] if event == "open" else [repr(args)[:200]]
        events.append([phase[0], event, *detail])


sys.addaudithook(hook)
from synapse_cdm.adapters import nsif_codec, nsif_geometry, stanag4545


def calls():
    adapter = stanag4545.Stanag4545Adapter()
    for raw in vectors:
        try:
            found = nsif_codec.parse_container(raw, nsif_codec.CORE1_LIMITS)
        except nsif_codec.NsifError:
            continue
        for index, image in enumerate(found.images):
            bands = tuple(range(image.band_count))
            nsif_codec.decode_nc_window(found, index, 0, 0, image.ncols, image.nrows, bands)
        try:
            adapter.to_cdm(raw)
        except nsif_codec.NsifError:
            pass
        nsif_geometry.footprint("G", raw[:60])


phase[0] = "warmup"
calls()
phase[0] = "calls"
calls()
phase[0] = "done"
print(json.dumps({"vectors": len(vectors), "events": events}))
"""


def test_invariant_10_no_network_or_file_access_from_core_imports_or_parser():
    """In a child interpreter with an audit hook installed after `synapse_cdm` and the standard
    library: the three adapter imports open only module files under the package (or the
    standard library) for reading, and parsing, decoding and translating every kit vector a
    second time opens nothing, connects nothing, spawns nothing and changes no file."""
    environment = {"PYTHONPATH": str(PACKAGE.parent), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [sys.executable, "-B", "-c", PROGRAM],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(PACKAGE),
        check=False,
        timeout=600,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout)
    assert record["vectors"] == 17
    roots = (str(PACKAGE) + "/", sysconfig.get_paths()["stdlib"] + "/")
    suffixes = (".py", ".pyc", *importlib.machinery.EXTENSION_SUFFIXES)
    imports = [event for event in record["events"] if event[0] == "imports"]
    assert imports, "the hook saw no import"
    for _, name, path, mode in imports:
        assert name == "open" and "w" not in mode and "a" not in mode and "+" not in mode, path
        assert path.endswith(suffixes) and path.startswith(roots), path
    # A module is read from its source or, when a valid cache exists, from its bytecode.
    opened = {pathlib.PurePosixPath(path).name.split(".")[0] for _, _, path, _ in imports}
    assert {"nsif_codec", "nsif_geometry", "stanag4545"} <= opened
    assert [event for event in record["events"] if event[0] == "calls"] == []


def test_invariant_11_caps_admit_the_limit_and_refuse_one_more(monkeypatch):
    """Output objects, serialised output, the window and the metadata charge, each at its limit
    and one over, with injected limits where the wire cannot reach the CORE-1 value."""
    raw = kit("geo_dms")
    objects = Stanag4545Adapter(clock=times.frozen_clock()).to_cdm(raw)
    assert len(objects) == 2
    size = len(("[" + ",".join(item.model_dump_json() for item in objects) + "]").encode("utf-8"))
    for limits, refusal in (
        (nc.Limits(output_objects=2), None),
        (nc.Limits(output_objects=1), ("E_LIMIT", "cdm", None, "/cdm/objects")),
        (nc.Limits(output_bytes=size), None),
        (nc.Limits(output_bytes=size - 1), ("E_LIMIT", "cdm", None, "/cdm/serialized")),
    ):
        monkeypatch.setattr(nc, "CORE1_LIMITS", limits)
        instance = Stanag4545Adapter(clock=times.frozen_clock())
        if refusal is None:
            assert len(instance.to_cdm(raw)) == 2
        else:
            with pytest.raises(nc.NsifError) as caught:
                instance.to_cdm(raw)
            error = caught.value
            assert (error.code, error.stage, error.offset, error.path) == refusal
    monkeypatch.setattr(nc, "CORE1_LIMITS", LIMITS)
    # The window: three bands of 7 x 5 16-bit samples are 210 octets.
    edge = NATIVE["native_edge16_b"]
    at_limit = nc.parse_container(edge, nc.Limits(window_bytes=210))
    assert len(nc.decode_nc_window(at_limit, 0, 0, 0, 7, 5, (0, 1, 2)).data) == 210
    over = nc.parse_container(edge, nc.Limits(window_bytes=209))
    with pytest.raises(nc.NsifError) as caught:
        nc.decode_nc_window(over, 0, 0, 0, 7, 5, (0, 1, 2))
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_LIMIT",
        "pixels",
        "/window",
    )
    # The metadata charge: HL 404 and one 439-octet image subheader are 843 octets.
    assert nc.parse_container(MONO, nc.Limits(metadata_bytes=843)).metadata_bytes == 843
    for limit, offset, path in (
        (842, 404, "/segments/image[0]/subheader"),
        (403, 354, "/file_header/HL"),
    ):
        with pytest.raises(nc.NsifError) as caught:
            nc.parse_container(MONO, nc.Limits(metadata_bytes=limit))
        error = caught.value
        assert (error.code, error.stage, error.offset, error.path) == (
            "E_LIMIT",
            "segment",
            offset,
            path,
        ), limit


def test_invariant_12_no_core_module_evaluates_its_input():
    """No call to eval, exec, compile or __import__ and no process, shell or pickle module in
    the three adapter modules: nothing a source holds can run (the gate that generates fuzz
    input is held to the same rule by tests/test_cdm_nsif_fuzz.py)."""
    banned_calls = {"eval", "exec", "compile", "__import__", "breakpoint"}
    banned_modules = {"subprocess", "os", "pickle", "marshal", "shelve", "importlib", "ctypes"}
    for name in ("nsif_codec.py", "nsif_geometry.py", "stanag4545.py"):
        tree = ast.parse((ADAPTERS / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned_calls, (name, node.func.id)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_modules, (name, alias.name)
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] not in banned_modules, (name, node.module)
