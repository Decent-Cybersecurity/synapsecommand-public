"""The preview: the integer arithmetic as literal tables, the selection rules, the lookup-table
case and its refusal, the standard-library PNG read back by an independent reader written here,
the derivative's provenance and reuse, and the separation from the analytic samples."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import struct
import sys
import zlib

import pytest
from conftest import LOCAL
from helpers import build_nsif, graphic, image, sha, vector

from synapse_cdm.adapters.nsif_codec import NsifError
from synapse_cdm.version import PACKAGE_VERSION
from synapse_imagery import preview
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.policy import Artefact
from synapse_imagery.result import HostError
from synapse_imagery.worker import Window, WorkerLimits, WorkerPool

SLOW_CHILD = str(pathlib.Path(__file__).with_name("slow_child.py"))
GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
LUT_TABLES = (bytes([0, 85, 170, 255]), bytes([255, 170, 85, 0]), bytes([10, 20, 30, 40]))


def lut3(samples=bytes([0, 1, 2, 3])) -> bytes:
    """The lookup-table vector: IREP RGB/LUT, one LU band, three tables of four entries; its
    band's LUTD field is at 798 and its data at 860."""
    octets = build_nsif([image(irep="RGB/LUT", irepband=b"LU", luts=LUT_TABLES, data=samples)])
    assert octets[792:798] == b"300004" and octets[798:810] == b"".join(LUT_TABLES)
    assert octets[860:] == samples
    return octets


# --------------------------------------------------------------------------- an independent reader


def _paeth(left: int, up: int, corner: int) -> int:
    estimate = left + up - corner
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
    return (left, up, corner)[distances.index(min(distances))]


def read_png(data: bytes):
    """(width, height, channels, rows of pixel tuples), from the chunks up: signature, CRC of
    every chunk, the inflated stream and every filter type undone."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    at, chunks = 8, []
    while at < len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        kind, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + length]
        (crc,) = struct.unpack(">I", data[at + 8 + length : at + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        chunks.append((kind, body))
        at += 12 + length
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, method, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    assert (depth, method, filtering, interlace) == (8, 0, 0, 0)
    channels = {0: 1, 2: 3}[colour]
    raw = zlib.decompress(chunks[1][1])
    stride = width * channels
    assert len(raw) == height * (stride + 1)
    previous = bytearray(stride)
    rows = []
    for y in range(height):
        kind, line = (
            raw[y * (stride + 1)],
            bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]),
        )
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            line[i] = (
                line[i] + (0, left, up, (left + up) // 2, _paeth(left, up, corner))[kind]
            ) & 0xFF
        previous = line
        pixels = [tuple(line[x * channels : (x + 1) * channels]) for x in range(width)]
        rows.append([p[0] if channels == 1 else p for p in pixels])
    return width, height, channels, rows


def test_the_independent_reader_reads_a_hand_made_file():
    # Filter 1 (sub) on a 2x1 grey image: 10, then +5.
    stream = zlib.compress(bytes([1, 10, 5]))
    header = struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0)

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    data = (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", stream) + chunk(b"IEND", b"")
    )
    assert read_png(data) == (2, 1, 1, [[10, 15]])


# --------------------------------------------------------------------------- the arithmetic


@pytest.mark.parametrize(
    "abpp, signed, values, shown",
    [
        (8, False, [0, 1, 127, 128, 255], [0, 1, 127, 128, 255]),
        (12, False, [0, 1, 2047, 2048, 4095], [0, 0, 127, 128, 255]),
        (16, False, [0, 128, 32767, 32768, 65535], [0, 0, 127, 128, 255]),
        (8, True, [-128, -1, 0, 127], [0, 127, 128, 255]),
        (12, True, [-2048, -1, 0, 2047], [0, 127, 128, 255]),
        (1, False, [0, 1], [0, 255]),
        (1, True, [-1, 0], [0, 255]),
        (16, False, [0, 256, 4095, 65535], [0, 1, 16, 255]),
    ],
)
def test_the_mono_mapping_is_linear_over_the_representable_range(abpp, signed, values, shown):
    assert [preview.display_value(v, abpp, signed) for v in values] == shown


@pytest.mark.parametrize(
    "source, size",
    [
        ((1024, 1024), (1024, 1024)),
        ((1025, 1), (1024, 1)),
        ((4000, 3000), (1024, 768)),
        ((3000, 1001), (1024, 342)),
        ((1001, 3000), (342, 1024)),
        ((100000, 1), (1024, 1)),
        ((1500, 1000), (1024, 683)),
        ((2000, 1000), (1024, 512)),
        ((2, 2), (2, 2)),
    ],
)
def test_the_preview_size_keeps_the_aspect_and_never_enlarges(source, size):
    assert preview.preview_size(*source) == size


@pytest.mark.parametrize(
    "src, dst_size, pairs",
    [
        (4000, 1024, [(0, 1), (1, 5), (511, 1998), (1023, 3998)]),
        (1001, 342, [(0, 1), (170, 499), (341, 999)]),
        (5, 5, [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]),
        (2000, 1024, [(0, 0), (1, 2), (2, 4), (1023, 1999)]),
    ],
)
def test_the_nearest_neighbour_index_is_the_fixed_formula(src, dst_size, pairs):
    assert [(dst, preview.source_index(dst, src, dst_size)) for dst, _ in pairs] == pairs


@pytest.mark.parametrize(
    "options",
    [
        {"bands": (0, 0, 1)},
        {"bands": (0, 1)},
        {"bands": (0, 1, 2, 3)},
        {"bands": ()},
        {"bands": [0]},
        {"bands": (-1,)},
        {"bands": (True,)},
        {"max_size": 0},
        {"max_size": 1025},
        {"max_size": True},
        {"max_size": 512.0},
    ],
)
def test_a_rendering_spec_outside_its_rule_is_refused(options):
    with pytest.raises(ValueError):
        preview.RenderingSpec(**options)


def test_the_png_writer_writes_exactly_its_three_chunks():
    data = preview.png_bytes(2, 1, 3, [bytes([1, 2, 3, 4, 5, 6])])
    assert read_png(data) == (2, 1, 3, [[(1, 2, 3), (4, 5, 6)]])
    assert data[12:16] == b"IHDR" and data[-8:-4] == b"IEND"
    with pytest.raises(ValueError):
        preview.png_bytes(2, 1, 2, [bytes(4)])
    with pytest.raises(ValueError):
        preview.png_bytes(2, 2, 1, [bytes(2)])


# --------------------------------------------------------------------------- through the service


def committed(services, store, octets, **options):
    service = services(store, worker=options.pop("worker", None) or InProcessWorker(), **options)
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "committed", result["diagnostics"]
    return service, result


def drawn(service, result, tmp_path, index=0, bands=None, name="preview.png"):
    output = tmp_path / name
    receipt = service.preview(result["record_id"], index, output, principal=LOCAL, bands=bands)
    return receipt, read_png(output.read_bytes()), output


def stored_derivative(store, receipt):
    return store.read_derivative(receipt["derivative_id"], tenant="local")


def test_a_mono_image_previews_as_its_samples(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    receipt, png, output = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[0, 64], [128, 255]])
    assert receipt == {
        "schema": "sc-imagery-preview/1",
        "record_id": result["record_id"],
        "derivative_id": receipt["derivative_id"],
        "image_index": 0,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "bytes": len(output.read_bytes()),
        "size": [2, 2],
        "channels": 1,
        "algorithm": "sc-imagery-linear-nearest/1",
        "selection": "automatic",
        "composition": "segment_only",
    }
    assert os.stat(output).st_mode & 0o777 == 0o600


def test_a_sixteen_bit_image_previews_in_eight_bits_and_its_source_is_untouched(
    services, store, tmp_path
):
    octets = vector("uint16.ntf")
    service, result = committed(services, store, octets)
    _, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[0, 1], [16, 255]])
    (path,) = pathlib.Path(store.root, "tenants").glob(f"*/originals/{result['asset_id']}")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha(octets)
    window = service.decode_window(
        result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL
    )
    assert window.window.values() == (0, 256, 4095, 65535)


# 8-bit samples with fewer significant bits than stored bits, drawn by the mapping over the
# representable range: ABPP 1 has span 1, so its two values become 0 and 255; ABPP 4 has span 15,
# so (v - lo) * 255 / 15 rounded is 0, 85, 170, 255 for 0, 5, 10, 15 (INT) and 0, 119, 136, 255
# for -8, -1, 0, 7 (SI, lo -8: 0, 1785/15 = 119.0, 2040/15 = 136.0, 3825/15 = 255); ABPP 7 has
# span 127, so 1 and 64 become 255/127 = 2.008 -> 2 and 16320/127 = 128.504 -> 129 (INT), and -1
# and 0 become 16065/127 = 126.496 -> 126 and 129 (SI, lo -64). Each storage octet is written by
# hand: PJUST R puts the value in the low bits, PJUST L in the high bits, and a signed value is
# its two's complement in ABPP bits; every fill bit is zero.
LOW_ABPP_CASES = [
    (1, "INT", "R", [0x00, 0x01, 0x01, 0x00], (0, 1, 1, 0), [[0, 255], [255, 0]]),
    (1, "INT", "L", [0x00, 0x80, 0x80, 0x00], (0, 1, 1, 0), [[0, 255], [255, 0]]),
    (1, "SI", "R", [0x01, 0x00, 0x00, 0x01], (-1, 0, 0, -1), [[0, 255], [255, 0]]),
    (1, "SI", "L", [0x80, 0x00, 0x00, 0x80], (-1, 0, 0, -1), [[0, 255], [255, 0]]),
    (4, "INT", "R", [0x00, 0x05, 0x0A, 0x0F], (0, 5, 10, 15), [[0, 85], [170, 255]]),
    (4, "INT", "L", [0x00, 0x50, 0xA0, 0xF0], (0, 5, 10, 15), [[0, 85], [170, 255]]),
    (4, "SI", "R", [0x08, 0x0F, 0x00, 0x07], (-8, -1, 0, 7), [[0, 119], [136, 255]]),
    (4, "SI", "L", [0x80, 0xF0, 0x00, 0x70], (-8, -1, 0, 7), [[0, 119], [136, 255]]),
    (7, "INT", "R", [0x00, 0x01, 0x40, 0x7F], (0, 1, 64, 127), [[0, 2], [129, 255]]),
    (7, "SI", "R", [0x40, 0x7F, 0x00, 0x3F], (-64, -1, 0, 63), [[0, 126], [129, 255]]),
]


def low_abpp(abpp, pvtype, pjust, stored) -> bytes:
    return build_nsif([image(abpp=abpp, pvtype=pvtype, pjust=pjust, data=bytes(stored))])


@pytest.mark.parametrize(
    "abpp, pvtype, pjust, stored, values, shown",
    LOW_ABPP_CASES,
    ids=[f"abpp{c[0]}-{c[1]}-{c[2]}" for c in LOW_ABPP_CASES],
)
def test_an_eight_bit_image_with_fewer_significant_bits_previews_over_its_range(
    services, store, tmp_path, abpp, pvtype, pjust, stored, values, shown
):
    service, result = committed(services, store, low_abpp(abpp, pvtype, pjust, stored))
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, shown)
    assert (receipt["algorithm"], receipt["selection"]) == (
        "sc-imagery-linear-nearest/1",
        "automatic",
    )
    # The analytic samples stay the interpreted values.
    window = service.decode_window(
        result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL
    )
    assert window.window.values() == values


def test_a_low_abpp_preview_through_the_isolated_worker(services, store, tmp_path):
    octets = low_abpp(4, "SI", "R", [0x08, 0x0F, 0x00, 0x07])
    service, result = committed(services, store, octets, worker=WorkerPool())
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[0, 119], [136, 255]])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert provenance["worker"]["isolation"] == "subprocess"
    octets = low_abpp(1, "INT", "L", [0x00, 0x80, 0x80, 0x00])
    service, result = committed(services, store, octets, worker=WorkerPool())
    _, png, _ = drawn(service, result, tmp_path, name="other.png")
    assert png == (2, 2, 1, [[0, 255], [255, 0]])


class _Window:
    """A decoded window as the renderer reads it, built here to hold a value no interpreted
    window can: the renderer must refuse it, not draw it."""

    def __init__(self, dtype, data):
        self.dtype, self.itemsize, self.data = dtype, 1, data


@pytest.mark.parametrize(
    "dtype, data, signed_abpp",
    [("uint8", bytes([0, 5, 10, 16]), 4), ("int8", bytes([0xF7, 0, 0, 0]), 4)],
)
def test_a_value_outside_the_significant_bits_is_never_drawn(dtype, data, signed_abpp):
    facts = preview.ImageFacts(
        index=0,
        irep="MONO",
        pvtype="SI" if dtype == "int8" else "INT",
        abpp=signed_abpp,
        ncols=2,
        nrows=2,
        native=True,
        bands=(preview.Band("M", 0, 0),),
        irep_offset=756,
        lut_offset=None,
    )
    chosen = preview.select(facts, preview.RenderingSpec())
    with pytest.raises(ValueError, match="outside the range its significant bits represent"):
        preview.render(_Window(dtype, data), facts, chosen, 1024)


def mode_b_rgb_rows():
    return [[(1 + 4 * r + c, 21 + 4 * r + c, 41 + 4 * r + c) for c in range(4)] for r in range(4)]


def test_an_explicit_selection_is_rgb_in_the_order_given(services, store, tmp_path):
    service, result = committed(services, store, vector("mode_B.ntf"))
    receipt, png, _ = drawn(service, result, tmp_path, bands=(0, 1, 2))
    assert png == (4, 4, 3, mode_b_rgb_rows())
    assert (receipt["selection"], receipt["channels"]) == ("explicit", 3)
    provenance = stored_derivative(store, receipt)["provenance"]
    assert (provenance["selection"], provenance["bands"], provenance["diagnostics"]) == (
        "explicit",
        [0, 1, 2],
        [],
    )
    _, png, _ = drawn(service, result, tmp_path, bands=(2, 0, 1), name="other.png")
    assert png[3][0][0] == (41, 1, 21)


def test_multi_bands_without_colour_descriptors_are_a_numeric_band_zero(services, store, tmp_path):
    service, result = committed(services, store, vector("mode_B.ntf"))
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (4, 4, 1, [[1 + 4 * r + c for c in range(4)] for r in range(4)])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert (provenance["selection"], provenance["bands"]) == ("automatic", [0])
    assert provenance["diagnostics"] == [
        {
            "code": "COLOUR_INTERPRETATION_UNRESOLVED",
            "stage": "pixels",
            "offset": 756,
            "path": "/segments/image[0]/IREP",
            "message": "colour interpretation is not resolved; a numeric band preview is shown",
        }
    ]


def three_bands(irep, descriptors):
    data = bytes([10, 11, 12, 13, 20, 21, 22, 23, 30, 31, 32, 33])
    return build_nsif([image(bands=3, irep=irep, irepbands=descriptors, data=data)])


@pytest.mark.parametrize("irep", ["RGB", "MULTI"])
def test_colour_descriptors_select_rgb_whatever_their_band_order(services, store, tmp_path, irep):
    service, result = committed(services, store, three_bands(irep, (b"B ", b"G ", b"R ")))
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 3, [[(30, 20, 10), (31, 21, 11)], [(32, 22, 12), (33, 23, 13)]])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert (provenance["selection"], provenance["bands"], provenance["diagnostics"]) == (
        "automatic",
        [2, 1, 0],
        [],
    )


@pytest.mark.parametrize(
    "irep, descriptors",
    [
        ("RGB", (b"R ", b"R ", b"B ")),
        ("RGB", (b"M ", b"M ", b"M ")),
        ("MULTI", (b"R ", b"G ", b"  ")),
    ],
)
def test_the_first_three_bands_are_never_assumed_to_be_colour(
    services, store, tmp_path, irep, descriptors
):
    service, result = committed(services, store, three_bands(irep, descriptors))
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[10, 11], [12, 13]])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert [entry["code"] for entry in provenance["diagnostics"]] == [
        "COLOUR_INTERPRETATION_UNRESOLVED"
    ]


def test_a_large_image_is_drawn_at_most_1024_wide_by_nearest_neighbour(services, store, tmp_path):
    # 2000 x 1000, samples 0, 64, 128, 255 repeating along each row: column c holds that of c % 4.
    service, result = committed(services, store, build_nsif([image(rows=1000, cols=2000)]))
    receipt, png, _ = drawn(service, result, tmp_path)
    width, height, channels, rows = png
    assert (width, height, channels) == (1024, 512, 1)
    assert receipt["size"] == [1024, 512]
    # Source columns 0, 2, 4 and 1999 for preview columns 0, 1, 2 and 1023.
    for row in (rows[0], rows[255], rows[511]):
        assert (row[0], row[1], row[2], row[1023]) == (0, 128, 0, 255)


def test_the_lookup_table_case_draws_the_three_tables(services, store, tmp_path):
    service, result = committed(services, store, lut3())
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 3, [[(0, 255, 10), (85, 170, 20)], [(170, 85, 30), (255, 0, 40)]])
    assert (receipt["algorithm"], receipt["selection"], receipt["channels"]) == (
        "sc-imagery-lut-nearest/1",
        "lut",
        3,
    )
    provenance = stored_derivative(store, receipt)["provenance"]
    assert provenance["parameters"]["mapping"] == (
        "the index band's three lookup tables as red, green and blue"
    )
    # The analytic samples stay the indexes.
    window = service.decode_window(
        result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL
    )
    assert window.window.values() == (0, 1, 2, 3)


def test_an_index_past_the_table_refuses_the_whole_preview(services, store, tmp_path):
    service, result = committed(services, store, lut3(bytes([0, 1, 2, 4])))
    with pytest.raises(NsifError) as caught:
        drawn(service, result, tmp_path)
    error = caught.value
    assert (error.code, error.stage, error.offset, error.path, error.explanation) == (
        "E_FIELD",
        "pixels",
        798,
        "/segments/image[0]/band[0]/LUTD",
        "a sample index is not smaller than the number of LUT entries",
    )
    assert store.list_derivatives(result["asset_id"], tenant="local") == []
    assert not (tmp_path / "preview.png").exists()
    assert os.listdir(pathlib.Path(store.root) / "staging") == []


@pytest.mark.parametrize(
    "options",
    [
        {"irep": "RGB/LUT", "irepband": b"LU", "luts": (bytes(4),)},
        {"irep": "MONO", "luts": (bytes(4),)},
        {"irep": "RGB/LUT", "irepband": b"M "},
    ],
)
def test_any_other_lookup_table_gives_a_numeric_preview(services, store, tmp_path, options):
    service, result = committed(services, store, build_nsif([image(**options)]))
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[0, 64], [128, 255]])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert provenance["algorithm"] == "sc-imagery-linear-nearest/1"
    assert [(entry["code"], entry["offset"]) for entry in provenance["diagnostics"]] == [
        ("COLOUR_INTERPRETATION_UNRESOLVED", 756)
    ]


def test_the_derivative_records_its_provenance(services, store, tmp_path):
    octets = vector("mono_nsif101.ntf")
    service, result = committed(services, store, octets)
    receipt, _, _ = drawn(service, result, tmp_path)
    stored = stored_derivative(store, receipt)
    provenance = stored["provenance"]
    assert provenance == {
        "algorithm": "sc-imagery-linear-nearest/1",
        "parameters": {
            "mapping": "linear over the representable significant-bit range",
            "downsampling": (
                "nearest neighbour, source index floor((dst+0.5)*src/dst_size) capped at src-1"
            ),
            "max_size": 1024,
        },
        "selection": "automatic",
        "bands": [0],
        "image_index": 0,
        "source_window": [0, 0, 2, 2],
        "size": [2, 2],
        "composition": "segment_only",
        "diagnostics": [],
        "parent_id": result["asset_id"],
        "parent_sha256": sha(octets),
        "software": {
            "synapse_imagery": "1.0.0",
            "synapse_cdm": PACKAGE_VERSION,
            "zlib": zlib.ZLIB_RUNTIME_VERSION,
        },
        "worker": provenance["worker"],
    }
    assert provenance["worker"]["isolation"] == "none"
    assert stored["recipe"] == {
        "algorithm": "sc-imagery-linear-nearest/1",
        "image_index": 0,
        "max_size": 1024,
        "selection": "automatic",
        "bands": [0],
        "software": provenance["software"],
    }
    record = store.read_record("local", result["record_id"], area="records")
    assert stored["descriptor"] == record["descriptor"]
    assert (stored["parent_id"], stored["parent_sha256"]) == (result["asset_id"], sha(octets))


def test_a_preview_of_a_file_with_graphics_says_they_were_not_composed(services, store, tmp_path):
    octets = build_nsif([image(icords="G", igeolo=GEO)], graphics=[graphic()])
    service, result = committed(services, store, octets)
    receipt, png, _ = drawn(service, result, tmp_path)
    assert png == (2, 2, 1, [[0, 64], [128, 255]])
    provenance = stored_derivative(store, receipt)["provenance"]
    assert (provenance["graphic_segments"], provenance["graphics_composed"]) == (1, False)
    assert provenance["composition"] == "segment_only"


def test_a_repeated_preview_reuses_its_derivative_without_a_worker_run(services, store, tmp_path):
    starts = tmp_path / "starts"
    pathlib.Path(str(starts) + ".release").write_text("go")
    pool = WorkerPool(_child_command=[sys.executable, "-I", "-B", SLOW_CHILD, "block", str(starts)])
    service = services(store, worker=InProcessWorker())
    result = service.ingest(
        vector("geo_dms.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    counting = services(store, worker=pool)
    try:
        first = counting.preview(result["record_id"], 0, tmp_path / "a.png", principal=LOCAL)
        assert len(starts.read_text().splitlines()) == 1
        second = counting.preview(result["record_id"], 0, tmp_path / "b.png", principal=LOCAL)
        assert len(starts.read_text().splitlines()) == 1
        assert first == second
        assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
        # Another selection is another derivative, and runs the worker.
        third = counting.preview(
            result["record_id"], 0, tmp_path / "c.png", principal=LOCAL, bands=(0,)
        )
        assert len(starts.read_text().splitlines()) == 2
        assert third["derivative_id"] != first["derivative_id"]
        assert third["selection"] == "explicit"
    finally:
        pool.shutdown(kill=True)


def test_a_preview_through_the_isolated_worker(services, store, tmp_path):
    service, result = committed(services, store, vector("mode_R.ntf"), worker=WorkerPool())
    receipt, png, _ = drawn(service, result, tmp_path, bands=(0, 1, 2))
    assert png == (4, 4, 3, mode_b_rgb_rows())
    provenance = stored_derivative(store, receipt)["provenance"]
    assert provenance["worker"]["isolation"] == "subprocess"
    assert provenance["worker"]["memory_enforcement"] == (
        "rlimit_as" if sys.platform.startswith("linux") else "not_enforced"
    )


def test_a_thumbnail_needs_its_own_approval(services, store, tmp_path):
    octets = vector("mono_nsif101.ntf")
    allow_all = FakePolicy({artefact: True for artefact in Artefact})
    service, result = committed(services, store, octets, policy=allow_all)
    denied = services(
        store,
        worker=InProcessWorker(),
        policy=FakePolicy({Artefact.METADATA: True, Artefact.ORIGINAL: True}),
    )
    with pytest.raises(HostError) as caught:
        denied.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/thumbnail")
    assert store.list_derivatives(result["asset_id"], tenant="local") == []
    thumbnails_only = services(
        store, worker=InProcessWorker(), policy=FakePolicy({Artefact.THUMBNAIL: True})
    )
    receipt = thumbnails_only.preview(result["record_id"], 0, tmp_path / "q.png", principal=LOCAL)
    assert receipt["size"] == [2, 2]


@pytest.mark.parametrize("bands", [(0, 0, 1), (0, 1), [0]])
def test_a_selection_outside_the_rule_is_refused_before_any_work(services, store, tmp_path, bands):
    service, result = committed(services, store, vector("mode_B.ntf"))
    with pytest.raises(ValueError):
        service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL, bands=bands)
    assert store.list_derivatives(result["asset_id"], tenant="local") == []


def test_a_band_the_image_does_not_have_is_the_window_decoders_refusal(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    with pytest.raises(NsifError) as caught:
        drawn(service, result, tmp_path, bands=(1,))
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_FIELD",
        "pixels",
        "/window/bands",
    )


def test_an_unknown_image_index_is_the_window_decoders_refusal(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    with pytest.raises(NsifError) as caught:
        drawn(service, result, tmp_path, index=1)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_FIELD",
        "pixels",
        "/window/image_index",
    )


def test_an_existing_output_is_not_replaced_unless_asked(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    output = tmp_path / "p.png"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        service.preview(result["record_id"], 0, output, principal=LOCAL)
    assert output.read_bytes() == b"keep"
    service.preview(result["record_id"], 0, output, principal=LOCAL, replace=True)
    assert read_png(output.read_bytes())[3] == [[0, 64], [128, 255]]
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix == ".part") == []


def test_a_preview_killed_at_its_deadline_leaves_no_derivative(services, store, tmp_path):
    octets = vector("mono_nsif101.ntf")
    service, result = committed(services, store, octets)
    starts = tmp_path / "starts"
    pool = WorkerPool(
        WorkerLimits(codec_deadline=0.5),
        _child_command=[sys.executable, "-I", "-B", SLOW_CHILD, "preview_partial", str(starts)],
    )
    try:
        killed = services(store, worker=pool)
        with pytest.raises(HostError) as caught:
            killed.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    finally:
        pool.shutdown(kill=True)
    assert (caught.value.code, caught.value.path) == ("E_TIMEOUT", "/worker")
    assert len(starts.read_text().splitlines()) == 2
    assert store.list_derivatives(result["asset_id"], tenant="local") == []
    assert not (tmp_path / "p.png").exists()
    assert os.listdir(pathlib.Path(store.root) / "staging") == []
    (path,) = pathlib.Path(store.root, "tenants").glob(f"*/originals/{result['asset_id']}")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha(octets)


def test_a_crashed_preview_child_leaves_no_derivative_and_is_not_retried(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    starts = tmp_path / "starts"
    pool = WorkerPool(_child_command=[sys.executable, "-I", "-B", SLOW_CHILD, "exit3", str(starts)])
    try:
        crashed = services(store, worker=pool)
        with pytest.raises(HostError) as caught:
            crashed.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    finally:
        pool.shutdown(kill=True)
    assert (caught.value.code, caught.value.path) == ("E_INTERNAL", "/worker")
    assert len(starts.read_text().splitlines()) == 1
    assert store.list_derivatives(result["asset_id"], tenant="local") == []
    assert os.listdir(pathlib.Path(store.root) / "staging") == []


def test_the_preview_and_its_record_hold_no_source_text(services, store, tmp_path):
    octets = build_nsif(
        [image(iid1="SECRETXYZ", isorce="SECRETXYZ", icords="G", igeolo=GEO)],
        ftitle="SECRETXYZ",
    )
    service, result = committed(services, store, octets)
    receipt, _, output = drawn(service, result, tmp_path)
    stored = json.dumps(stored_derivative(store, receipt)) + json.dumps(receipt)
    for needle in ("SECRETXYZ", "480000N", "0170000E"):
        assert needle not in stored
        assert needle.encode() not in output.read_bytes()
