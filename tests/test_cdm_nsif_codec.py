"""The SC4545-CORE-1 container parser and native window decoder, `adapters/nsif_codec.py`: the
byte primitives, the error model, the limits, the parsed-twin decoder, the file header, directory,
segment walk, extension areas, TREs, overflow resolution, the five subheaders, the non-fatal
inventory, the kit's 17 vectors with their builder, and the decoder over the kit's image vectors
and the native vectors under `fixtures/stanag4545/vectors/`.

Every expectation here is a literal: an offset derived by hand from the field widths of the
specification (the two layouts are written out below), the code, stage and path the specification
assigns to a condition (its section 19 table and the requirement that states the condition), a
digest, outcome or band-major sample list copied from the kit's `expected.json`, a sample value
written out by hand, or GDAL's recorded reading under `fixtures/stanag4545/independent/`. No
expected sample is computed with the interleave formulas under test: the native vectors are laid
out by the packaged builder's `physical_payload`, which only appends in each mode's wire order, so
its input planes are the expectation for what it wrote. The other containers are built by the
small builder in this module, which writes fields in the specification's order and knows nothing
of the parser. Package-only: every path is anchored on the imported package and nothing is written
outside `tmp_path`.

THE TWO LAYOUTS
---------------
L1 is `mono_nsif101.ntf`'s layout, 847 octets: the 360-octet prefix, a 44-octet directory (HL 404),
one 439-octet image subheader at 404 and four data octets at 843. L5 adds one segment of every
other kind, 1844 octets: directory to 447, image 447 (data 886), graphic 890 (data 1148, three
octets), text 1151 (data 1433, five), DES 1438 (data 1638, four), RES 1642 (data 1842, two).
"""

from __future__ import annotations

import ast
import base64
import copy
import dataclasses
import datetime
import hashlib
import inspect
import itertools
import json
import pathlib
import pickle
import re
import tracemalloc
import types

import pytest

import synapse_cdm
from synapse_cdm import harness
from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters import nsif_codec as nc
from tests import observation_support as support

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "stanag4545"
CODEC = PACKAGE / "adapters" / "nsif_codec.py"
LIMITS = nc.CORE1_LIMITS

#: Copied from the kit's `fixtures/expected.json`, the 17 `sha256` values by file name.
KIT_VECTOR_SHA256 = {
    "mono_nsif101.ntf": "934a6382dae1f512b4d7c7b426507f017725a92b1bf7d9694c48ee4c6acb8cc8",
    "mono_nsif100.ntf": "436a7d7aa77a4a21faf5590849412d1e0aa5dd4f70292916f0a49af47c4599ad",
    "mono_nitf210.ntf": "4dc3a218dc49394cf9b1fe23afd5ebd27bc2469e247475a8757e540f2038cec9",
    "geo_dms.ntf": "8848dd25910e03aaca8596ee4800b1dcd660dbb92a0ea31f22814267fc8d61d4",
    "unknown_duplicate_tre.ntf": "bfa3feec7d309097fc23268b9ae3406bd0b0d967e44169db2ff9184f18f224a2",
    "mode_B.ntf": "5b184def682d6f0a02b07e0c3cca7fb15ca62206e0f450baa1c90ef82f8f17ca",
    "mode_P.ntf": "bcbf4f7cafaa0395675d712cd9d44fedfd10d0f0ba1e7f7887574aaf0c16d6f8",
    "mode_R.ntf": "09ffe8ed581c75ec811ec5d177abdde45c98e4ef4fc869cc6a06e8819fdf3f00",
    "mode_S.ntf": "869bcbdd2c43a594aaf46dff71ebf6f2718599b648645ba3a689b516c1d831f6",
    "uint16.ntf": "77c8be04836b0e086dd19c895747184dfb982805fbffa78854babc82549f1fd6",
    "image_and_text.ntf": "68d11c0d3123b3a20ce2140db95b1c4844359b2f0cf7a8346098a89613310f48",
    "header_only.ntf": "e6f5af50b4b59b86ff0008ea06987ff5f9f345055b76b120a448f38ddecb877f",
    "bad_file_length.ntf": "dbd7f1edae1f325e7846a86588f72bfb5a9ca013bcc0a32328ebe47257c28385",
    "truncated.ntf": "54e7a8d93c2a59301f48b28c9969124e29bb7690a98a234757cb4ad27dc33c99",
    "trailing.ntf": "689588b79af9a73db5b985cd46efa78d1721f5aa216741095de616de78bd8f0f",
    "bad_count.ntf": "ca1ac997db6b82cfc66f4da292a60cb994e8ad42d00285a08f08b7d6003949ed",
    "unsupported_stype.ntf": "8eac401a58f51d3b063ee67e854f2c311fb07c0b263c2395b7b0b03a563b0274",
}

#: Where each kit vector is packaged: the eleven translatable ones at the top level.
KIT_PATHS = {
    **{
        name: name
        for name in (
            "mono_nsif101.ntf",
            "mono_nsif100.ntf",
            "mono_nitf210.ntf",
            "geo_dms.ntf",
            "unknown_duplicate_tre.ntf",
            "mode_B.ntf",
            "mode_P.ntf",
            "mode_R.ntf",
            "mode_S.ntf",
            "uint16.ntf",
            "image_and_text.ntf",
        )
    },
    "header_only.ntf": "context/header_only.ntf",
    **{
        name: f"malformed/{name}"
        for name in (
            "bad_file_length.ntf",
            "truncated.ntf",
            "trailing.ntf",
            "bad_count.ntf",
            "unsupported_stype.ntf",
        )
    },
}

#: `expected.json`'s `bytes` and `expected` per vector, and for a refusal the offset, stage and
#: path of the field the refusal is about (FL against the input length, a letter in NUMI, STYPE).
KIT_OUTCOMES = {
    "mono_nsif101.ntf": (847, "ok", None),
    "mono_nsif100.ntf": (847, "ok", None),
    "mono_nitf210.ntf": (847, "ok", None),
    "geo_dms.ntf": (907, "ok", None),
    "unknown_duplicate_tre.ntf": (878, "ok", None),
    "mode_B.ntf": (917, "ok", None),
    "mode_P.ntf": (917, "ok", None),
    "mode_R.ntf": (917, "ok", None),
    "mode_S.ntf": (917, "ok", None),
    "uint16.ntf": (851, "ok", None),
    "image_and_text.ntf": (1177, "ok", None),
    "header_only.ntf": (388, "ok", None),
    "bad_file_length.ntf": (847, "E_LENGTH", ("header", 342, "/file_header/FL")),
    "truncated.ntf": (846, "E_LENGTH", ("header", 342, "/file_header/FL")),
    "trailing.ntf": (848, "E_LENGTH", ("header", 342, "/file_header/FL")),
    "bad_count.ntf": (847, "E_DIGITS", ("header", 360, "/file_header/NUMI")),
    "unsupported_stype.ntf": (847, "E_PROFILE", ("header", 11, "/file_header/STYPE")),
}

#: The 29 kit-derived files the builder owns: the 17 vectors and the twins of the twelve that
#: parse.
KIT_BUILDER_PATHS = sorted(
    [KIT_PATHS[name] for name in KIT_PATHS]
    + [f"{name[:-4]}.parsed.json" for name, where in KIT_PATHS.items() if "/" not in where]
    + ["context/header_only.parsed.json"]
)

#: The 47 native vectors under `vectors/`, by stem: the asymmetric literal vector and the two
#: edge-block vectors in the four modes, the zero and padded block sizes, the fifteen
#: interpretation vectors, nine, ten and 256 bands in the four modes, the LUT vector and the four
#: rectangles.
NATIVE_STEMS = (
    *(f"native_lit_{m}" for m in "bprs"),
    *(f"native_edge8_{m}" for m in "bprs"),
    *(f"native_edge16_{m}" for m in "bprs"),
    "native_nppb_zero",
    "native_nppbh_zero_only",
    "native_one_block_padded",
    "native_pjust_r_12in16_dirty",
    "native_pjust_l_12in16",
    "native_pjust_l_12in16_dirty",
    "native_pjust_l_5in8",
    "native_si8",
    "native_si16",
    "native_si12_r_zerofill",
    "native_si12_r_signext",
    "native_si12_r_mixed",
    "native_si12_l",
    "native_si12_l_dirty",
    "native_si1in8_r",
    "native_int8in16_r",
    "native_int5in8_r_dirty",
    "native_si5in8_l_dirty",
    *(f"native_nbands9_{m}" for m in "bprs"),
    *(f"native_xbands10_{m}" for m in "bprs"),
    *(f"native_xbands256_{m}" for m in "bprs"),
    "native_lut3",
    "native_geo_g_northup",
    "native_geo_g_southup",
    "native_geo_d_northup",
    "native_geo_d_southup",
)

#: The eleven image-bearing kit vectors, by stem.
KIT_IMAGE_STEMS = tuple(name[:-4] for name, where in KIT_PATHS.items() if "/" not in where)

#: GDAL's readings under `independent/`, one per image-bearing vector.
READING_STEMS = (*KIT_IMAGE_STEMS, *NATIVE_STEMS)

#: Every file the builder owns: the kit-derived 29 and the 47 native vectors.
BUILDER_PATHS = sorted(KIT_BUILDER_PATHS + [f"vectors/{stem}.ntf" for stem in NATIVE_STEMS])


def _build_fixtures_module():
    """The packaged builder, loaded from SOURCE and never from bytecode, through `FIXTURES` read
    at call time (the loader contract every adapter test module keeps;
    `tests/test_cdm_generator_loading.py` explains the bytecode hazard the in-memory compile
    avoids)."""
    path = FIXTURES / "spec" / "build_fixtures.py"
    module = types.ModuleType("stanag4545_build_fixtures")
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def kit(name: str) -> bytes:
    return (FIXTURES / KIT_PATHS[name]).read_bytes()


# --------------------------------------------------------------------------- the builder


def _a(text: str | bytes, width: int) -> bytes:
    octets = text if isinstance(text, bytes) else text.encode("ascii")
    assert len(octets) <= width
    return octets.ljust(width, b" ")


def _d(value: int, width: int) -> bytes:
    octets = str(value).zfill(width).encode("ascii")
    assert len(octets) == width
    return octets


SEC_U = b"U" + b" " * 166
BAND = b"M " + b" " * 6 + b"N" + b" " * 3 + b"0"
PIXELS = b"\x00\x40\x80\xff"

HEADER = (
    ("FHDR", b"NSIF"),
    ("FVER", b"01.01"),
    ("CLEVEL", b"03"),
    ("STYPE", b"BF01"),
    ("OSTAID", _a("SCTEST", 10)),
    ("FDT", b"20261004120000"),
    ("FTITLE", _a("SYNTHETIC TEST VECTOR", 80)),
    ("security", SEC_U),
    ("FSCOP", b"00000"),
    ("FSCPYS", b"00000"),
    ("ENCRYP", b"0"),
    ("FBKGC", b"\x00\x00\x00"),
    ("ONAME", _a("SYNAPSECOMMAND TEST", 24)),
    ("OPHONE", _a("", 18)),
)
IMAGE = (
    ("IM", b"IM"),
    ("IID1", _a("SCTEST0001", 10)),
    ("IDATIM", b"20261004120000"),
    ("TGTID", _a("", 17)),
    ("IID2", _a("SYNTHETIC TEST IMAGE", 80)),
    ("security", SEC_U),
    ("ENCRYP", b"0"),
    ("ISORCE", _a("SYNTHETIC", 42)),
    ("NROWS", b"00000002"),
    ("NCOLS", b"00000002"),
    ("PVTYPE", b"INT"),
    ("IREP", _a("MONO", 8)),
    ("ICAT", _a("VIS", 8)),
    ("ABPP", b"08"),
    ("PJUST", b"R"),
    ("ICORDS", b" "),
    ("IGEOLO", b""),
    ("NICOM", b"0"),
    ("ICOM", b""),
    ("IC", b"NC"),
    ("COMRAT", b""),
    ("NBANDS", b"1"),
    ("XBANDS", b""),
    ("BANDS", BAND),
    ("ISYNC", b"0"),
    ("IMODE", b"B"),
    ("NBPR", b"0001"),
    ("NBPC", b"0001"),
    ("NPPBH", b"0002"),
    ("NPPBV", b"0002"),
    ("NBPP", b"08"),
    ("IDLVL", b"001"),
    ("IALVL", b"000"),
    ("ILOC", b"0000000000"),
    ("IMAG", b"1.0 "),
    ("UDID", b"00000"),
    ("IXSHD", b"00000"),
)
GRAPHIC = (
    ("SY", b"SY"),
    ("SID", _a("SCGRAPH01", 10)),
    ("SNAME", _a("SYNTHETIC GRAPHIC", 20)),
    ("security", SEC_U),
    ("ENCRYP", b"0"),
    ("SFMT", b"C"),
    ("SSTRUCT", b"0" * 13),
    ("SDLVL", b"002"),
    ("SALVL", b"001"),
    ("SLOC", b"0000000000"),
    ("SBND1", b"0000000000"),
    ("SCOLOR", b"C"),
    ("SBND2", b"0000100001"),
    ("SRES2", b"00"),
    ("SXSHD", b"00000"),
)
TEXT = (
    ("TE", b"TE"),
    ("TEXTID", _a("TXT001", 7)),
    ("TXTALVL", b"000"),
    ("TXTDT", b"20261004120000"),
    ("TXTITL", _a("SYNTHETIC TEXT", 80)),
    ("security", SEC_U),
    ("ENCRYP", b"0"),
    ("TXTFMT", b"STA"),
    ("TXSHD", b"00000"),
)
DES = (
    ("DE", b"DE"),
    ("DESID", _a("SYNTHETIC_DES", 25)),
    ("DESVER", b"01"),
    ("security", SEC_U),
    ("DESOFLW", b""),
    ("DESITEM", b""),
    ("DESSHL", b"0000"),
    ("DESSHF", b""),
)
RES = (
    ("RE", b"RE"),
    ("RESID", _a("SYNTHETIC_RES", 25)),
    ("RESVER", b"01"),
    ("security", SEC_U),
    ("RESSHL", b"0000"),
    ("RESSHF", b""),
)


def _fields(table, over) -> bytes:
    names = [name for name, _ in table]
    assert set(over) <= set(names), set(over) - set(names)
    return b"".join(over.get(name, value) for name, value in table)


def image_sh(**over) -> bytes:
    return _fields(IMAGE, over)


def graphic_sh(**over) -> bytes:
    return _fields(GRAPHIC, over)


def text_sh(**over) -> bytes:
    return _fields(TEXT, over)


def des_sh(**over) -> bytes:
    return _fields(DES, over)


def overflow_des_sh(section: str = "IXSHD", item: int = 1, **over) -> bytes:
    fields = {
        "DESID": _a("TRE_OVERFLOW", 25),
        "DESOFLW": _a(section, 6),
        "DESITEM": _d(item, 3),
        **over,
    }
    return _fields(DES, fields)


def res_sh(**over) -> bytes:
    return _fields(RES, over)


def tre(tag: bytes, data: bytes, cel: bytes | None = None) -> bytes:
    return tag + (_d(len(data), 5) if cel is None else cel) + data


def area(tres: bytes = b"", overflow: bytes | None = None) -> bytes:
    """`00000` when the area holds nothing, else L, the overflow number and the TREs."""
    if not tres and overflow is None:
        return b"00000"
    return _d(3 + len(tres), 5) + (overflow or b"000") + tres


def container(
    images=None,
    graphics=(),
    texts=(),
    des=(),
    res=(),
    *,
    udhd=b"00000",
    xhd=b"00000",
    numx=b"000",
    after_directory=b"",
    hl=None,
    fl=None,
    **over,
) -> bytes:
    if images is None:
        images = [(image_sh(), PIXELS)]
    prefix = _fields(HEADER, over)
    directory = _d(len(images), 3) + b"".join(_d(len(s), 6) + _d(len(p), 10) for s, p in images)
    directory += _d(len(graphics), 3) + b"".join(_d(len(s), 4) + _d(len(p), 6) for s, p in graphics)
    directory += numx
    directory += _d(len(texts), 3) + b"".join(_d(len(s), 4) + _d(len(p), 5) for s, p in texts)
    directory += _d(len(des), 3) + b"".join(_d(len(s), 4) + _d(len(p), 9) for s, p in des)
    directory += _d(len(res), 3) + b"".join(_d(len(s), 4) + _d(len(p), 7) for s, p in res)
    directory += udhd + xhd + after_directory
    body = b"".join(s + p for group in (images, graphics, texts, des, res) for s, p in group)
    header_length = 360 + len(directory) if hl is None else hl
    file_length = 360 + len(directory) + len(body) if fl is None else fl
    return prefix + _d(file_length, 12) + _d(header_length, 6) + directory + body


def l5(**over) -> bytes:
    parts = {
        "images": [(image_sh(), PIXELS)],
        "graphics": [(graphic_sh(), b"CGM")],
        "texts": [(text_sh(), b"HELLO")],
        "des": [(des_sh(), b"DATA")],
        "res": [(res_sh(), b"RS")],
    }
    parts.update(over)
    return container(**parts)


def put(raw: bytes, offset: int, octets: bytes) -> bytes:
    assert offset + len(octets) <= len(raw)
    return raw[:offset] + octets + raw[offset + len(octets) :]


def parse(raw: bytes, limits: nc.Limits = LIMITS) -> nc.Container:
    return nc.parse_container(raw, limits)


def refusal(raw: bytes, limits: nc.Limits = LIMITS) -> tuple:
    with pytest.raises(nc.NsifError) as caught:
        nc.parse_container(raw, limits)
    error = caught.value
    return (error.code, error.stage, error.offset, error.path)


def diagnostics(found: nc.Container) -> list[tuple]:
    return [(d.code, d.stage, d.offset, d.path) for d in found.diagnostics]


def test_the_builder_writes_the_two_layouts_this_module_states():
    """L1 is mono_nsif101's layout field for field; L5 is 1844 octets."""
    raw = container()
    assert len(raw) == 847
    assert raw[354:360] == b"000404"
    assert len(image_sh()) == 439
    assert len(graphic_sh()) == 258 and len(text_sh()) == 282
    assert len(des_sh()) == 200 and len(res_sh()) == 200 and len(overflow_des_sh()) == 209
    assert len(l5()) == 1844 and l5()[354:360] == b"000447"
    mono = kit("mono_nsif101.ntf")
    # The two differ only in descriptive and identifier text: every structural octet agrees.
    for offset, width in ((0, 15), (342, 62), (737, 106)):
        assert raw[offset : offset + width] == mono[offset : offset + width]


# =========================================================================== REQ-078: the kit


@pytest.mark.parametrize("name", sorted(KIT_VECTOR_SHA256))
def test_every_kit_vector_is_tracked_byte_identical_to_the_kit(name):
    octets = kit(name)
    assert len(octets) == KIT_OUTCOMES[name][0]
    assert hashlib.sha256(octets).hexdigest() == KIT_VECTOR_SHA256[name]


@pytest.mark.parametrize("name", sorted(KIT_OUTCOMES))
def test_every_kit_vector_has_the_kits_parse_level_outcome(name):
    _, expected, refused = KIT_OUTCOMES[name]
    octets = kit(name)
    if expected == "ok":
        found = parse(octets)
        assert found.file_size == len(octets)
        assert found.diagnostics == ()
        assert found.composition_status == "segment_only"
        assert [(i.pixel_status, i.pixel_reason) for i in found.images] == [
            ("native_supported", None)
        ] * len(found.images)
    else:
        assert refusal(octets) == (expected, *refused)
        with pytest.raises(nc.NsifError) as caught:
            parse(octets)
        stage, offset, path = refused
        assert str(caught.value).split(":")[0] == f"{expected} @byte {offset} {path}"


def test_the_kit_vectors_carry_the_signature_and_segments_the_kit_states():
    signatures = {
        "mono_nsif101.ntf": "NSIF01.01",
        "mono_nsif100.ntf": "NSIF01.00",
        "mono_nitf210.ntf": "NITF02.10",
    }
    for name, signature in signatures.items():
        found = parse(kit(name))
        assert found.signature == signature
        assert found.clevel == 3
        assert [(s.kind, s.subheader, s.data) for s in found.segments] == [
            ("image", nc.Slice(404, 439), nc.Slice(843, 4))
        ]
    assert parse(kit("header_only.ntf")).segments == ()
    assert parse(kit("header_only.ntf")).header_length == 388
    found = parse(kit("image_and_text.ntf"))
    assert [(s.kind, s.index, s.file_index, s.subheader, s.data) for s in found.segments] == [
        ("image", 0, 0, nc.Slice(413, 439), nc.Slice(852, 4)),
        ("text", 0, 1, nc.Slice(856, 282), nc.Slice(1138, 39)),
    ]
    for name in ("mode_B.ntf", "mode_P.ntf", "mode_R.ntf", "mode_S.ntf"):
        image = parse(kit(name)).images[0]
        assert (image.imode, image.band_count, image.nbpr, image.nbpc) == (name[5], 3, 2, 2)
        assert (image.block_width, image.block_height, image.segment.data.length) == (2, 2, 48)
    assert parse(kit("uint16.ntf")).images[0].nbpp == 16
    geo = parse(kit("geo_dms.ntf")).images[0]
    assert geo.icords == "G" and geo.igeolo == nc.Slice(776, 60)


def test_the_builder_owns_exactly_the_packaged_payloads_and_reproduces_them():
    built = _build_fixtures_module().fixtures()
    assert sorted(built) == BUILDER_PATHS
    assert len(KIT_BUILDER_PATHS) == 29 and len(NATIVE_STEMS) == len(set(NATIVE_STEMS)) == 47
    assert len(built) == 76
    tracked = sorted(
        p.relative_to(FIXTURES).as_posix()
        for p in FIXTURES.rglob("*")
        if p.is_file()
        and p.name not in ("README.md", "PROVENANCE.json")
        and not {"golden", "independent", "spec", "__pycache__"}
        & set(p.relative_to(FIXTURES).parts)
    )
    assert tracked == BUILDER_PATHS
    for relative, octets in built.items():
        assert (FIXTURES / relative).read_bytes() == octets, relative


def test_the_builder_imports_only_the_standard_library_set_and_checks_current(tmp_path):
    source = (FIXTURES / "spec" / "build_fixtures.py").read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "argparse", "base64", "json", "pathlib", "struct", "sys"}
    assert support.builder_problems(FIXTURES, tmp_path) == []


def test_every_twin_is_the_canonical_envelope_of_its_vector_and_decodes_to_it():
    for relative in KIT_BUILDER_PATHS:
        if not relative.endswith(".parsed.json"):
            continue
        octets = (FIXTURES / relative.replace(".parsed.json", ".ntf")).read_bytes()
        text = (FIXTURES / relative).read_text()
        document = {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(octets).decode()}
        assert text == json.dumps(document, indent=2) + "\n"
        assert nc.decode_twin(json.loads(text), LIMITS) == octets
        assert parse(nc.decode_twin(json.loads(text), LIMITS)) == parse(octets)


def test_the_fixture_tree_records_are_complete():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    selected = sorted(p.name for p in harness.select_fixtures(FIXTURES))
    assert selected == sorted(n for n in KIT_BUILDER_PATHS if "/" not in n) and len(selected) == 22
    assert sorted(p.name for p in harness.select_fixtures(FIXTURES / "context")) == [
        "header_only.ntf",
        "header_only.parsed.json",
    ]
    assert len(harness.select_fixtures(FIXTURES / "malformed")) == 5
    assert sorted(p.name for p in harness.select_fixtures(FIXTURES / "vectors")) == sorted(
        f"{stem}.ntf" for stem in NATIVE_STEMS
    )
    readings = sorted(p.name for p in harness.select_fixtures(FIXTURES / "independent"))
    assert readings == sorted(
        [*(f"{stem}.gdal.json" for stem in READING_STEMS), "gdal_reading.json"]
    )
    for directory in (
        FIXTURES,
        FIXTURES / "malformed",
        FIXTURES / "context",
        FIXTURES / "vectors",
        FIXTURES / "independent",
    ):
        record = json.loads((directory / "PROVENANCE.json").read_text())
        names = sorted(e["file"] for e in record["fixtures"])
        on_disk = sorted(
            p.name
            for p in directory.iterdir()
            if p.is_file() and p.name not in ("README.md", "PROVENANCE.json")
        )
        assert names == on_disk
        assert all(
            e["synthetic"] is True and e["classification"] == "PUBLIC" for e in record["fixtures"]
        )


# =========================================================================== REQ-018: primitives


def test_take_claims_a_slice_and_refuses_truncation_at_the_field_start():
    cursor = nc.Cursor(b"ABCDEFGH", 2, 7, "/p", "header")
    assert cursor.take(3, "X") == 2
    assert cursor.fields == {"X": nc.Slice(2, 3)} and cursor.pos == 5
    assert cursor.take(0, "Z") == 5
    with pytest.raises(nc.NsifError) as caught:
        cursor.take(3, "Y")
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_LENGTH",
        "header",
        5,
        "/p/Y",
    )
    assert cursor.take(2, "W") == 5 and cursor.pos == 7
    for bad in (-1, True, 1.0):
        with pytest.raises(TypeError):
            cursor.take(bad, "N")


@pytest.mark.parametrize(
    "octets",
    [
        b"+01",
        b" 01",
        b"01 ",
        b"-01",
        b"1.0",
        b"1e2",
        b"0x1",
        "١٢".encode(),
        b"\x00\x00",
        # The two neighbours of 0x30-0x39.
        b"/01",
        b":01",
        b"01/",
        b"01:",
    ],
)
def test_decimal_accepts_only_ascii_digits_and_never_strips(octets):
    cursor = nc.Cursor(b"##" + octets, 2, 2 + len(octets), "/f", "segment")
    with pytest.raises(nc.NsifError) as caught:
        cursor.decimal(len(octets), "N")
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_DIGITS",
        "segment",
        2,
        "/f/N",
    )


def test_decimal_reads_the_exact_integer():
    cursor = nc.Cursor(b"0070000000999999999999", 0, 22, "/f", "header")
    assert cursor.decimal(3, "A") == 7
    assert cursor.decimal(7, "B") == 0
    assert cursor.decimal(12, "C") == 999_999_999_999


def test_ascii_refuses_octets_outside_printable_and_trims_trailing_spaces_only():
    cursor = nc.Cursor(b" AB  ", 0, 5, "/f", "segment")
    assert cursor.ascii(5, "E") == " AB"
    assert cursor.fields["E"] == nc.Slice(0, 5)
    for octet in (b"\x00", b"\x1f", b"\x7f", b"\x80", b"\xff"):
        cursor = nc.Cursor(b"A" + octet + b"C", 0, 3, "/f", "segment")
        with pytest.raises(nc.NsifError) as caught:
            cursor.ascii(3, "E")
        assert (caught.value.code, caught.value.offset, caught.value.path) == ("E_FIELD", 0, "/f/E")


def test_bounded_subcursor_reads_only_its_slice():
    parent = nc.Cursor(b"0123456789", 1, 10, "/owner", "segment")
    child = parent.bounded_subcursor(4, "AREA", stage="extension")
    assert (child.pos, child.end, child.path, child.stage) == (1, 5, "/owner", "extension")
    assert parent.pos == 5 and parent.fields["AREA"] == nc.Slice(1, 4)
    assert child.decimal(3, "OFL") == 123
    with pytest.raises(nc.NsifError) as caught:
        child.take(2, "REST")
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_LENGTH",
        "extension",
        4,
        "/owner/REST",
    )
    with pytest.raises(nc.NsifError) as caught:
        parent.bounded_subcursor(6, "MORE")
    assert (caught.value.code, caught.value.offset, caught.value.path) == (
        "E_LENGTH",
        5,
        "/owner/MORE",
    )


def test_structural_numbers_on_the_wire_are_refused_unstripped():
    mono = kit("mono_nsif101.ntf")
    assert refusal(put(mono, 360, b"+01")) == ("E_DIGITS", "header", 360, "/file_header/NUMI")
    assert refusal(put(mono, 360, b" 01")) == ("E_DIGITS", "header", 360, "/file_header/NUMI")
    assert refusal(put(mono, 737, b"      02")) == (
        "E_DIGITS",
        "segment",
        737,
        "/segments/image[0]/NROWS",
    )
    assert refusal(put(mono, 793, b"X")) == ("E_DIGITS", "segment", 793, "/segments/image[0]/ISYNC")
    assert refusal(l5(texts=[(text_sh(TXTALVL=b"0A0"), b"HELLO")])) == (
        "E_DIGITS",
        "segment",
        1160,
        "/segments/text[0]/TXTALVL",
    )


# The field classes as a literal table, every field of both layouts in wire order with
# its offset and width, and the outcome a probe octet gives in each class:
#   S  structural decimal: a space -> E_DIGITS at the field (nothing is stripped first)
#   SX an extension length field: a space -> E_DIGITS at the field, stage extension
#   E  enumerated: 0x00 -> E_FIELD at the field
#   D  descriptive: 0x00 -> parsed, one TEXT_UNINTERPRETED at the field
#   R  raw: 0x00 -> parsed, no diagnostic
#   L  raw with the tolerant location reading: 0x00 -> parsed, LOCATION_UNINTERPRETED
#   T  date: 0x00 -> parsed, DATE_MALFORMED
#   SEC security block: 0x00 -> parsed, no diagnostic
#   exact values: 0x00 -> the code given (E_MAGIC for the signature, E_PROFILE for STYPE, E_FIELD
#   for a marker, PJUST, IMODE, IC and ENCRYP)
L1_HEADER = (
    ("FHDR", 0, 4, "E_MAGIC"),
    ("FVER", 4, 5, "E_MAGIC"),
    ("CLEVEL", 9, 2, "S"),
    ("STYPE", 11, 4, "E_PROFILE"),
    ("OSTAID", 15, 10, "D"),
    ("FDT", 25, 14, "T"),
    ("FTITLE", 39, 80, "D"),
    ("security", 119, 167, "SEC"),
    ("FSCOP", 286, 5, "R"),
    ("FSCPYS", 291, 5, "R"),
    ("ENCRYP", 296, 1, "E_FIELD"),
    ("FBKGC", 297, 3, "R"),
    ("ONAME", 300, 24, "D"),
    ("OPHONE", 324, 18, "D"),
    ("FL", 342, 12, "S"),
    ("HL", 354, 6, "S"),
    ("NUMI", 360, 3, "S"),
    ("LISH[0]", 363, 6, "S"),
    ("LI[0]", 369, 10, "S"),
    ("NUMS", 379, 3, "S"),
    ("NUMX", 382, 3, "S"),
    ("NUMT", 385, 3, "S"),
    ("NUMDES", 388, 3, "S"),
    ("NUMRES", 391, 3, "S"),
    ("UDHDL", 394, 5, "SX"),
    ("XHDL", 399, 5, "SX"),
)
L1_IMAGE = (
    ("IM", 404, 2, "E_FIELD"),
    ("IID1", 406, 10, "D"),
    ("IDATIM", 416, 14, "T"),
    ("TGTID", 430, 17, "D"),
    ("IID2", 447, 80, "D"),
    ("security", 527, 167, "SEC"),
    ("ENCRYP", 694, 1, "E_FIELD"),
    ("ISORCE", 695, 42, "D"),
    ("NROWS", 737, 8, "S"),
    ("NCOLS", 745, 8, "S"),
    ("PVTYPE", 753, 3, "E"),
    ("IREP", 756, 8, "E"),
    ("ICAT", 764, 8, "E"),
    ("ABPP", 772, 2, "S"),
    ("PJUST", 774, 1, "E_FIELD"),
    ("ICORDS", 775, 1, "E"),
    ("NICOM", 776, 1, "S"),
    ("IC", 777, 2, "E_FIELD"),
    ("NBANDS", 779, 1, "S"),
    ("band[0]/IREPBAND", 780, 2, "E"),
    ("band[0]/ISUBCAT", 782, 6, "R"),
    ("band[0]/IFC", 788, 1, "R"),
    ("band[0]/IMFLT", 789, 3, "R"),
    ("band[0]/NLUTS", 792, 1, "S"),
    ("ISYNC", 793, 1, "S"),
    ("IMODE", 794, 1, "E_FIELD"),
    ("NBPR", 795, 4, "S"),
    ("NBPC", 799, 4, "S"),
    ("NPPBH", 803, 4, "S"),
    ("NPPBV", 807, 4, "S"),
    ("NBPP", 811, 2, "S"),
    ("IDLVL", 813, 3, "S"),
    ("IALVL", 816, 3, "S"),
    ("ILOC", 819, 10, "L"),
    ("IMAG", 829, 4, "R"),
    ("UDIDL", 833, 5, "SX"),
    ("IXSHDL", 838, 5, "SX"),
)
L5_GRAPHIC = (
    ("SY", 890, 2, "E_FIELD"),
    ("SID", 892, 10, "D"),
    ("SNAME", 902, 20, "D"),
    ("security", 922, 167, "SEC"),
    ("ENCRYP", 1089, 1, "E_FIELD"),
    ("SFMT", 1090, 1, "E"),
    ("SSTRUCT", 1091, 13, "R"),
    ("SDLVL", 1104, 3, "S"),
    ("SALVL", 1107, 3, "S"),
    ("SLOC", 1110, 10, "L"),
    ("SBND1", 1120, 10, "L"),
    ("SCOLOR", 1130, 1, "E"),
    ("SBND2", 1131, 10, "L"),
    ("SRES2", 1141, 2, "R"),
    ("SXSHDL", 1143, 5, "SX"),
)
L5_TEXT = (
    ("TE", 1151, 2, "E_FIELD"),
    ("TEXTID", 1153, 7, "D"),
    ("TXTALVL", 1160, 3, "S"),
    ("TXTDT", 1163, 14, "T"),
    ("TXTITL", 1177, 80, "D"),
    ("security", 1257, 167, "SEC"),
    ("ENCRYP", 1424, 1, "E_FIELD"),
    ("TXTFMT", 1425, 3, "E"),
    ("TXSHDL", 1428, 5, "SX"),
)
L5_DES = (
    ("DE", 1438, 2, "E_FIELD"),
    ("DESID", 1440, 25, "E"),
    ("DESVER", 1465, 2, "R"),
    ("security", 1467, 167, "SEC"),
    ("DESSHL", 1634, 4, "S"),
    ("DESSHF", 1638, 0, None),
)
L5_RES = (
    ("RE", 1642, 2, "E_FIELD"),
    ("RESID", 1644, 25, "E"),
    ("RESVER", 1669, 2, "R"),
    ("security", 1671, 167, "SEC"),
    ("RESSHL", 1838, 4, "S"),
    ("RESSHF", 1842, 0, None),
)
L5_DIRECTORY = (
    ("NUMI", 360, 3, "S"),
    ("LISH[0]", 363, 6, "S"),
    ("LI[0]", 369, 10, "S"),
    ("NUMS", 379, 3, "S"),
    ("LSSH[0]", 382, 4, "S"),
    ("LS[0]", 386, 6, "S"),
    ("NUMX", 392, 3, "S"),
    ("NUMT", 395, 3, "S"),
    ("LTSH[0]", 398, 4, "S"),
    ("LT[0]", 402, 5, "S"),
    ("NUMDES", 407, 3, "S"),
    ("LDSH[0]", 410, 4, "S"),
    ("LD[0]", 414, 9, "S"),
    ("NUMRES", 423, 3, "S"),
    ("LRESH[0]", 426, 4, "S"),
    ("LRE[0]", 430, 7, "S"),
    ("UDHDL", 437, 5, "SX"),
    ("XHDL", 442, 5, "SX"),
)

_DIAGNOSED = {"D": "TEXT_UNINTERPRETED", "L": "LOCATION_UNINTERPRETED", "T": "DATE_MALFORMED"}


def _class_cases():
    for layout, prefix, table in (
        ("L1", "/file_header", L1_HEADER),
        ("L1", "/segments/image[0]", L1_IMAGE),
        ("L5", "/file_header", L5_DIRECTORY),
        ("L5", "/segments/graphic[0]", L5_GRAPHIC),
        ("L5", "/segments/text[0]", L5_TEXT),
        ("L5", "/segments/des[0]", L5_DES),
        ("L5", "/segments/res[0]", L5_RES),
    ):
        for name, offset, _width, kind in table:
            if kind is not None:
                yield pytest.param(
                    layout, prefix, name, offset, kind, id=f"{layout}{prefix}/{name}"
                )


@pytest.mark.parametrize("layout, prefix, name, offset, kind", list(_class_cases()))
def test_every_field_behaves_as_its_class(layout, prefix, name, offset, kind):
    raw = container() if layout == "L1" else l5()
    stage = "header" if prefix == "/file_header" else "segment"
    path = f"{prefix}/{name}"
    if kind in ("S", "SX"):
        expected = ("E_DIGITS", "extension" if kind == "SX" else stage, offset, path)
        assert refusal(put(raw, offset, b" ")) == expected
        return
    probed = put(raw, offset, b"\x00")
    if kind in ("R", "SEC"):
        assert diagnostics(parse(probed)) == []
    elif kind in _DIAGNOSED:
        assert diagnostics(parse(probed)) == [(_DIAGNOSED[kind], stage, offset, path)]
    elif kind == "E":
        assert refusal(probed) == ("E_FIELD", stage, offset, path)
    elif name in ("FHDR", "FVER"):
        assert refusal(probed) == ("E_MAGIC", "header", 0, "/file_header/FHDR")
    elif name in ("IM", "SY", "TE", "DE", "RE"):
        assert refusal(probed) == ("E_FIELD", stage, offset, path)
    else:
        assert refusal(probed) == (kind, stage, offset, path)


def test_every_record_keeps_its_fields_in_wire_order_with_their_widths():
    mono = parse(container())
    assert [(n, s.offset, s.length) for n, s in mono.file_header.fields.items()] == [
        (n, o, w) for n, o, w, _ in L1_HEADER
    ]
    assert [(n, s.offset, s.length) for n, s in mono.images[0].fields.items()] == [
        (n, o, w) for n, o, w, _ in L1_IMAGE
    ]
    five = parse(l5())
    for record, table in (
        (five.graphics[0], L5_GRAPHIC),
        (five.texts[0], L5_TEXT),
        (five.des[0], L5_DES),
        (five.res[0], L5_RES),
    ):
        assert [(n, s.offset, s.length) for n, s in record.fields.items()] == [
            (n, o, w) for n, o, w, _ in table
        ]
    directory = [(n, s.offset, s.length) for n, s in five.file_header.fields.items()][16:]
    assert directory == [(n, o, w) for n, o, w, _ in L5_DIRECTORY]


# =========================================================================== REQ-019: text


def test_ascii_text_exposes_printable_text_or_none_beside_the_raw_slice():
    raw = b"ABC  " + b"A\x07" + b"  AB" + b"\xe9t\xe9" + b"AB\t" + b"\x7f"
    assert nc.ascii_text(raw, nc.Slice(0, 5)) == ("ABC", "printable_ascii")
    assert nc.ascii_text(raw, nc.Slice(5, 2)) == (None, "uninterpreted")
    assert nc.ascii_text(raw, nc.Slice(7, 4)) == ("  AB", "printable_ascii")
    assert nc.ascii_text(raw, nc.Slice(11, 3)) == (None, "uninterpreted")
    assert nc.ascii_text(raw, nc.Slice(14, 3)) == (None, "uninterpreted")
    assert nc.ascii_text(raw, nc.Slice(17, 1)) == (None, "uninterpreted")
    assert nc.ascii_text(raw, nc.Slice(0, 0)) == ("", "printable_ascii")


def test_uninterpreted_text_keeps_its_slice_and_gives_one_diagnostic_per_structure():
    mono = kit("mono_nsif101.ntf")
    found = parse(put(mono, 39, b"\xe9"))
    assert diagnostics(found) == [("TEXT_UNINTERPRETED", "header", 39, "/file_header/FTITLE")]
    assert found.file_header.fields["FTITLE"] == nc.Slice(39, 80)
    assert nc.ascii_text(found.raw, found.file_header.fields["FTITLE"]) == (None, "uninterpreted")
    # The first non-printable descriptive field of each structure, one diagnostic each.
    found = parse(put(put(put(put(mono, 15, b"\x00"), 39, b"\xe9"), 406, b"\xff"), 447, b"\x01"))
    assert diagnostics(found) == [
        ("TEXT_UNINTERPRETED", "header", 15, "/file_header/OSTAID"),
        ("TEXT_UNINTERPRETED", "segment", 406, "/segments/image[0]/IID1"),
    ]
    comments = image_sh(NICOM=b"2", ICOM=_a("FIRST", 80) + b"\x9b" + b" " * 79)
    found = parse(container(images=[(comments, PIXELS)]))
    assert diagnostics(found) == [
        ("TEXT_UNINTERPRETED", "segment", 857, "/segments/image[0]/ICOM[1]")
    ]


def test_widths_count_octets_and_display_values_trim_trailing_spaces_only():
    title = "été".encode() + b" " * 75
    found = parse(container(FTITLE=title))
    assert found.file_header.fields["FTITLE"] == nc.Slice(39, 80)
    assert found.file_header.security.slice == nc.Slice(119, 167)
    found = parse(container(images=[(image_sh(PVTYPE=b"SI ", IREP=b" MONO   "), PIXELS)]))
    image = found.images[0]
    assert (image.pvtype, image.irep, image.icat, image.bands[0].irepband) == (
        "SI",
        " MONO",
        "VIS",
        "M",
    )
    assert image.fields["IREP"] == nc.Slice(756, 8)
    assert image.pixel_status == "native_supported"


# =========================================================================== REQ-020: dates

UTC = datetime.timezone.utc


@pytest.mark.parametrize(
    "octets, status, value",
    [
        (b"20261004120000", "valid", datetime.datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)),
        (b"20240229235959", "valid", datetime.datetime(2024, 2, 29, 23, 59, 59, tzinfo=UTC)),
        (b"20000229000000", "valid", datetime.datetime(2000, 2, 29, 0, 0, 0, tzinfo=UTC)),
        (b"00010101000000", "valid", datetime.datetime(1, 1, 1, 0, 0, 0, tzinfo=UTC)),
        (b"99991231235959", "valid", datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)),
        (b" " * 14, "unknown", None),
        (b"0" * 14, "unknown", None),
        (b"2026----------", "partial", None),
        (b"-" * 14, "partial", None),
        (b"20161231235960", "leap_second", None),
        (b"2026100412000Z", "malformed", None),
        (b"2026100412    ", "malformed", None),
        (b" 0261004120000", "malformed", None),
        (b"2026-10-04 120", "malformed", None),
        (b"20260230120000", "impossible", None),
        (b"20230229120000", "impossible", None),
        (b"20260229120000", "impossible", None),
        (b"20220229120000", "impossible", None),
        (b"21000229120000", "impossible", None),
        (b"20261304120000", "impossible", None),
        (b"20260000000000", "impossible", None),
        (b"20261000120000", "impossible", None),
        (b"20261004240000", "impossible", None),
        (b"20261004126000", "impossible", None),
        (b"20261004120061", "impossible", None),
        (b"00001004120000", "impossible", None),
        (b"20260230120060", "impossible", None),
    ],
)
def test_the_one_date_classifier(octets, status, value):
    assert nc.classify_date(octets) == (status, value)


@pytest.mark.parametrize(
    "octets, code",
    [
        (b" " * 14, "DATE_UNKNOWN"),
        (b"0" * 14, "DATE_UNKNOWN"),
        (b"2026----------", "DATE_PARTIAL"),
        (b"20161231235960", "TIME_UNRESOLVED"),
        (b"2026100412000Z", "DATE_MALFORMED"),
    ],
)
def test_an_uninterpreted_date_is_kept_with_its_diagnostic(octets, code):
    found = parse(put(kit("mono_nsif101.ntf"), 25, octets))
    assert diagnostics(found) == [(code, "header", 25, "/file_header/FDT")]
    assert found.file_header.fdt.slice == nc.Slice(25, 14)
    assert found.file_header.fdt.value is None
    assert found.file_header.fdt.status == nc.classify_date(octets)[0]
    found = parse(put(kit("mono_nsif101.ntf"), 416, octets))
    assert diagnostics(found) == [(code, "segment", 416, "/segments/image[0]/IDATIM")]
    found = parse(put(kit("image_and_text.ntf"), 868, octets))
    assert diagnostics(found) == [(code, "segment", 868, "/segments/text[0]/TXTDT")]


def test_only_a_malformed_date_is_a_violation_of_the_profile():
    listed = {code for code, flag in nc.DIAGNOSTIC_CODES.items() if flag}
    assert "DATE_MALFORMED" in listed
    assert not {"DATE_UNKNOWN", "DATE_PARTIAL", "TIME_UNRESOLVED"} & listed


def test_an_impossible_date_is_fatal_in_every_date_field():
    for octets in (b"20260230120000", b"20261004126000", b"20260229120000"):
        assert refusal(put(kit("mono_nsif101.ntf"), 25, octets)) == (
            "E_FIELD",
            "header",
            25,
            "/file_header/FDT",
        )
        assert refusal(put(kit("mono_nsif101.ntf"), 416, octets)) == (
            "E_FIELD",
            "segment",
            416,
            "/segments/image[0]/IDATIM",
        )
        assert refusal(put(kit("image_and_text.ntf"), 868, octets)) == (
            "E_FIELD",
            "segment",
            868,
            "/segments/text[0]/TXTDT",
        )


def test_a_valid_date_is_a_utc_instant_and_security_dates_are_never_parsed():
    found = parse(kit("mono_nsif101.ntf"))
    assert found.file_header.fdt == nc.DateValue(
        nc.Slice(25, 14), "valid", datetime.datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    )
    assert found.images[0].idatim.value == datetime.datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    # DCDT, DGDT and SRDT of the file block (contract FSDCDT 157, FSDGDT 170, FSSRDT 263) and of
    # the image block (527 + 38, + 51, + 144) hold impossible and non-digit dates: labels only.
    raw = kit("mono_nsif101.ntf")
    for offset in (157, 170, 263, 565, 578, 671):
        raw = put(raw, offset, b"99999999" if offset % 2 else b"\xff\xff\xff\xff\xff\xff\xff\xff")
    assert diagnostics(parse(raw)) == []


# =========================================================================== REQ-021: the prefix

#: bundle/contracts/file-header-fields.json, copied: (field, offset, bytes).
CONTRACT = (
    ("FHDR", 0, 4),
    ("FVER", 4, 5),
    ("CLEVEL", 9, 2),
    ("STYPE", 11, 4),
    ("OSTAID", 15, 10),
    ("FDT", 25, 14),
    ("FTITLE", 39, 80),
    ("FSCLAS", 119, 1),
    ("FSCLSY", 120, 2),
    ("FSCODE", 122, 11),
    ("FSCTLH", 133, 2),
    ("FSREL", 135, 20),
    ("FSDCTP", 155, 2),
    ("FSDCDT", 157, 8),
    ("FSDCXM", 165, 4),
    ("FSDG", 169, 1),
    ("FSDGDT", 170, 8),
    ("FSCLTX", 178, 43),
    ("FSCAPT", 221, 1),
    ("FSCAUT", 222, 40),
    ("FSCRSN", 262, 1),
    ("FSSRDT", 263, 8),
    ("FSCTLN", 271, 15),
    ("FSCOP", 286, 5),
    ("FSCPYS", 291, 5),
    ("ENCRYP", 296, 1),
    ("FBKGC", 297, 3),
    ("ONAME", 300, 24),
    ("OPHONE", 324, 18),
    ("FL", 342, 12),
    ("HL", 354, 6),
)


@pytest.mark.parametrize("name", [n for n in KIT_OUTCOMES if KIT_OUTCOMES[n][1] == "ok"])
def test_the_prefix_slices_are_the_contracts_offsets(name):
    header = parse(kit(name)).file_header
    for field, offset, width in CONTRACT:
        if field.startswith("FS") and field not in ("FSCOP", "FSCPYS"):
            assert header.security.fields[field[2:]] == nc.Slice(offset, width), field
        else:
            assert header.fields[field] == nc.Slice(offset, width), field
    assert sum(width for _, _, width in CONTRACT) == 360


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda m: m[:8], ("E_LENGTH", "header", 0, "/file_header/FHDR")),
        (lambda m: b"", ("E_LENGTH", "header", 0, "/file_header/FHDR")),
        (lambda m: put(m, 0, b"NITF02.00"), ("E_MAGIC", "header", 0, "/file_header/FHDR")),
        (lambda m: put(m, 0, b"nsif01.01"), ("E_MAGIC", "header", 0, "/file_header/FHDR")),
        (lambda m: m[:10], ("E_LENGTH", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"0A"), ("E_DIGITS", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"04"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"10"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"00"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"01"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"02"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: put(m, 9, b"08"), ("E_PROFILE", "header", 9, "/file_header/CLEVEL")),
        (lambda m: m[:13], ("E_LENGTH", "header", 11, "/file_header/STYPE")),
        (lambda m: put(m, 11, b"bf01"), ("E_PROFILE", "header", 11, "/file_header/STYPE")),
        (lambda m: m[:30], ("E_LENGTH", "header", 25, "/file_header/FDT")),
        (lambda m: m[:200], ("E_LENGTH", "header", 119, "/file_header/security")),
        (lambda m: put(m, 296, b"1"), ("E_ENCRYPTED", "header", 296, "/file_header/ENCRYP")),
        (lambda m: put(m, 296, b"X"), ("E_FIELD", "header", 296, "/file_header/ENCRYP")),
        (lambda m: m[:350], ("E_LENGTH", "header", 342, "/file_header/FL")),
        (lambda m: put(m, 342, b"00000000084A"), ("E_DIGITS", "header", 342, "/file_header/FL")),
        (lambda m: put(m, 342, b"999999999999"), ("E_LENGTH", "header", 342, "/file_header/FL")),
        (lambda m: put(m, 342, b"000000000000"), ("E_LENGTH", "header", 342, "/file_header/FL")),
        (lambda m: m + m, ("E_LENGTH", "header", 342, "/file_header/FL")),
        (lambda m: put(m, 354, b"0004O4"), ("E_DIGITS", "header", 354, "/file_header/HL")),
        (lambda m: put(m, 354, b"000387"), ("E_LENGTH", "header", 354, "/file_header/HL")),
        (lambda m: put(m, 354, b"000848"), ("E_LENGTH", "header", 354, "/file_header/HL")),
    ],
)
def test_every_prefix_rule_refuses_with_its_code_at_its_field(mutate, expected):
    assert refusal(mutate(kit("mono_nsif101.ntf"))) == expected


def test_the_accepted_prefix_values():
    mono = kit("mono_nsif101.ntf")
    for clevel in (b"03", b"05", b"06", b"07", b"09"):
        assert parse(put(mono, 9, clevel)).clevel == int(clevel)
    found = parse(put(mono, 297, b"\xff\x00\x80"))
    assert found.file_header.fields["FBKGC"] == nc.Slice(297, 3)
    assert found.raw[297:300] == b"\xff\x00\x80"
    header_only = kit("header_only.ntf")
    assert header_only[342:360] == b"000000000388000388"
    assert parse(header_only).file_size == 388
    assert parse(kit("mono_nsif100.ntf")).signature == "NSIF01.00"
    assert parse(kit("mono_nitf210.ntf")).signature == "NITF02.10"


# =========================================================================== REQ-022: directory and walk


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            put(kit("mono_nsif101.ntf"), 382, b"001"),
            ("E_PROFILE", "header", 382, "/file_header/NUMX"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 382, b"0X1"),
            ("E_DIGITS", "header", 382, "/file_header/NUMX"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 360, b"065"),
            ("E_LIMIT", "header", 360, "/file_header/NUMI"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 369, b"000000000A"),
            ("E_DIGITS", "header", 369, "/file_header/LI[0]"),
        ),
        (put(l5(), 414, b"00000000A"), ("E_DIGITS", "header", 414, "/file_header/LD[0]")),
        (put(l5(), 426, b"02O0"), ("E_DIGITS", "header", 426, "/file_header/LRESH[0]")),
        (
            put(kit("mono_nsif101.ntf"), 354, b"000388"),
            ("E_LENGTH", "header", 388, "/file_header/NUMDES"),
        ),
        # HL one short of 404: the XHDL field (399 to 403) crosses it, which is an extension
        # area's length field crossing its enclosing end, so the stage is extension.
        (
            put(kit("mono_nsif101.ntf"), 354, b"000403"),
            ("E_LENGTH", "extension", 399, "/file_header/XHDL"),
        ),
        (container(after_directory=b" "), ("E_LENGTH", "header", 404, "/file_header")),
    ],
)
def test_the_directory_rules(raw, expected):
    assert refusal(raw) == expected


def test_the_walk_locates_every_segment_from_the_lengths_in_file_order():
    found = parse(l5())
    assert [(s.kind, s.index, s.file_index, s.subheader, s.data) for s in found.segments] == [
        ("image", 0, 0, nc.Slice(447, 439), nc.Slice(886, 4)),
        ("graphic", 0, 1, nc.Slice(890, 258), nc.Slice(1148, 3)),
        ("text", 0, 2, nc.Slice(1151, 282), nc.Slice(1433, 5)),
        ("des", 0, 3, nc.Slice(1438, 200), nc.Slice(1638, 4)),
        ("res", 0, 4, nc.Slice(1642, 200), nc.Slice(1842, 2)),
    ]
    assert found.segments[-1].data.offset + found.segments[-1].data.length == found.file_size


def test_the_walk_refuses_lengths_that_do_not_end_at_fl():
    mono = kit("mono_nsif101.ntf")
    assert refusal(put(mono, 369, b"0000000003")) == ("E_LENGTH", "segment", 846, "/segments")
    assert refusal(put(mono, 369, b"0000000005")) == (
        "E_LENGTH",
        "segment",
        843,
        "/segments/image[0]/data",
    )
    assert refusal(put(mono, 363, b"999999")) == (
        "E_LENGTH",
        "segment",
        404,
        "/segments/image[0]/subheader",
    )


@pytest.mark.parametrize(
    "li, data",
    [(3, b"\x00\x40\x80"), (5, b"\x00\x40\x80\xff\x00"), (0, b"")],
)
def test_a_native_image_whose_data_length_is_not_its_sample_length_is_refused(li, data):
    raw = container(images=[(image_sh(), data)])
    assert refusal(raw) == ("E_LENGTH", "segment", 843, "/segments/image[0]/data")


def test_a_non_native_image_keeps_any_data_length():
    float32 = image_sh(PVTYPE=b"R  ", ABPP=b"32", NBPP=b"32")
    found = parse(container(images=[(float32, b"")]))
    assert found.images[0].pixel_status == "unsupported"
    assert found.images[0].segment.data == nc.Slice(843, 0)
    single = image_sh(IMODE=b"S")
    assert parse(container(images=[(single, b"\x01\x02\x03")])).images[0].pixel_reason == (
        "unsupported_sample_layout"
    )


def test_a_zero_length_subheader_fails_at_its_marker_and_zero_data_is_inventoried():
    assert refusal(container(texts=[(b"", b"")])) == (
        "E_LENGTH",
        "segment",
        856,
        "/segments/text[0]/TE",
    )
    found = parse(l5(texts=[(text_sh(), b"")]))
    assert found.texts[0].segment.data == nc.Slice(1433, 0)


def test_a_subheader_shorter_than_its_grammar_fails_at_the_first_field_that_does_not_fit():
    assert refusal(container(images=[(image_sh()[:-2], PIXELS)])) == (
        "E_LENGTH",
        "extension",
        838,
        "/segments/image[0]/IXSHDL",
    )
    assert refusal(container(images=[(image_sh()[:200], PIXELS)])) == (
        "E_LENGTH",
        "segment",
        527,
        "/segments/image[0]/security",
    )


# =========================================================================== REQ-023: no search


def test_marker_and_magic_spellings_in_fields_and_data_change_nothing():
    plain = parse(l5())
    spelled = l5(
        images=[(image_sh(IID2=_a("IMNSIF01.01IMSYTEDERE", 80)), b"IMIM")],
        graphics=[(graphic_sh(SNAME=_a("NITF02.10IMSY", 20)), b"IM ")],
        texts=[(text_sh(TXTITL=_a("TE IM NSIF01.00 DE RE", 80)), b"NSIF0")],
    )
    found = parse(put(spelled, 39, b"IM NSIF01.01 IMIMIM SYSYSY TETE"))
    assert found.segments == plain.segments
    assert [r.fields for r in found.images] == [r.fields for r in plain.images]


def test_file_order_is_kept_while_display_levels_differ():
    found = parse(
        container(
            images=[
                (image_sh(IDLVL=b"002", IID1=_a("SECOND", 10)), PIXELS),
                (image_sh(IDLVL=b"001", IID1=_a("FIRST", 10)), PIXELS),
            ]
        )
    )
    assert [(i.index, i.segment.file_index, i.idlvl) for i in found.images] == [
        (0, 0, 2),
        (1, 1, 1),
    ]
    assert [nc.ascii_text(found.raw, i.fields["IID1"])[0] for i in found.images] == [
        "SECOND",
        "FIRST",
    ]
    assert found.composition_status == "segment_only"


def test_a_des_holding_a_whole_container_stays_opaque():
    embedded = kit("mono_nsif101.ntf")
    found = parse(container(des=[(des_sh(), embedded)]))
    assert len(found.images) == 1 and len(found.des) == 1
    assert found.des[0].segment.data == nc.Slice(1060, 847)
    assert found.extensions == () and found.diagnostics == ()
    found = parse(container(des=[(des_sh(DESID=_a("XML_DATA_CONTENT", 25)), b"<a><b/></a>")]))
    assert found.des[0].desid == "XML_DATA_CONTENT" and found.des[0].desoflw is None


# =========================================================================== REQ-029: areas

AREA_CASES = {
    # area -> (container with an L of 2 in that area, content start, OFL path)
    "UDHD": (lambda: container(udhd=b"0000200"), 399, "/file_header/UDHOFL"),
    "XHD": (lambda: container(xhd=b"0000200"), 404, "/file_header/XHDLOFL"),
    "UDID": (
        lambda: container(images=[(image_sh(UDID=b"0000200"), PIXELS)]),
        838,
        "/segments/image[0]/UDOFL",
    ),
    "IXSHD": (
        lambda: container(images=[(image_sh(IXSHD=b"0000200"), PIXELS)]),
        843,
        "/segments/image[0]/IXSOFL",
    ),
    "SXSHD": (
        lambda: l5(graphics=[(graphic_sh(SXSHD=b"0000200"), b"CGM")]),
        1148,
        "/segments/graphic[0]/SXSOFL",
    ),
    "TXSHD": (
        lambda: l5(texts=[(text_sh(TXSHD=b"0000200"), b"HELLO")]),
        1433,
        "/segments/text[0]/TXSOFL",
    ),
}


@pytest.mark.parametrize("section", sorted(AREA_CASES))
def test_every_area_follows_the_same_length_rule(section):
    build, start, path = AREA_CASES[section]
    assert refusal(build()) == ("E_LENGTH", "extension", start, path)


def test_the_length_rule_of_one_area():
    def with_area(octets):
        return container(images=[(image_sh(IXSHD=octets), PIXELS)])

    found = parse(with_area(b"00000"))
    assert found.images[0].ixshd == nc.ExtensionArea(
        "IXSHD", "image", 0, nc.Slice(838, 5), 0, None, 0, nc.Slice(843, 0), ()
    )
    found = parse(with_area(b"00003000"))
    assert found.images[0].ixshd == nc.ExtensionArea(
        "IXSHD", "image", 0, nc.Slice(838, 5), 3, nc.Slice(843, 3), 0, nc.Slice(846, 0), ()
    )
    assert refusal(with_area(b"000010")) == (
        "E_LENGTH",
        "extension",
        843,
        "/segments/image[0]/IXSOFL",
    )
    assert refusal(with_area(b"0001000A")) == (
        "E_LENGTH",
        "extension",
        843,
        "/segments/image[0]/IXSHD",
    )
    assert refusal(with_area(b"0000A")) == (
        "E_DIGITS",
        "extension",
        838,
        "/segments/image[0]/IXSHDL",
    )
    assert refusal(with_area(b"000030X0")) == (
        "E_DIGITS",
        "extension",
        843,
        "/segments/image[0]/IXSOFL",
    )
    # Five octets of the file header's areas, read inside the header that ends at HL.
    assert refusal(container(udhd=b"00009ABC")) == (
        "E_LENGTH",
        "extension",
        399,
        "/file_header/UDHD",
    )


def test_des_and_res_user_subheaders_are_not_extension_areas():
    found = parse(
        l5(
            des=[(des_sh(DESSHL=b"0008", DESSHF=b"00003000"), b"DATA")],
            res=[(res_sh(RESSHL=b"0005", RESSHF=b"00002"), b"RS")],
        )
    )
    assert found.des[0].user_subheader == nc.Slice(1638, 8)
    assert found.res[0].user_subheader == nc.Slice(1850, 5)
    assert [a.section for a in found.areas] == ["UDHD", "XHD", "UDID", "IXSHD", "SXSHD", "TXSHD"]
    assert found.extensions == ()


# =========================================================================== REQ-030: TREs


def test_the_kits_duplicate_unknown_tres_are_two_ordered_records():
    found = parse(kit("unknown_duplicate_tre.ntf"))
    assert found.extensions == (
        nc.Extension(
            "IXSHD", "image", 0, 0, "local", None, "SCZZZZ", nc.Slice(846, 14), nc.Slice(857, 3)
        ),
        nc.Extension(
            "IXSHD", "image", 0, 1, "local", None, "SCZZZZ", nc.Slice(860, 14), nc.Slice(871, 3)
        ),
    )
    assert type(found.extensions) is tuple
    assert found.images[0].ixshd.tres == found.extensions
    assert found.raw[857:860] == b"abc" and found.raw[871:874] == b"def"


def _one_tre(octets: bytes) -> bytes:
    return container(images=[(image_sh(IXSHD=area(octets)), PIXELS)])


@pytest.mark.parametrize(
    "octets, expected",
    [
        (
            tre(b"bad   ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (
            tre(b"      ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (
            tre(b"AB-CD ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        # The neighbours of A-Z (0x40, 0x5B) and of 0-9 (0x2F, 0x3A).
        (
            tre(b"AB@CD ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (
            tre(b"AB[CD ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (
            tre(b"AB/CD ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (
            tre(b"AB:CD ", b""),
            ("E_FIELD", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG"),
        ),
        (b"ABC", ("E_LENGTH", "extension", 846, "/segments/image[0]/IXSHD/tre[0]/CETAG")),
        (b"ABCDEF12", ("E_LENGTH", "extension", 852, "/segments/image[0]/IXSHD/tre[0]/CEL")),
        (b"ABCDEF0000X", ("E_DIGITS", "extension", 852, "/segments/image[0]/IXSHD/tre[0]/CEL")),
        (
            b"ABCDEF00010xyz",
            ("E_LENGTH", "extension", 857, "/segments/image[0]/IXSHD/tre[0]/CEDATA"),
        ),
        (
            tre(b"ABCDEF", b"") + b"ABC",
            ("E_LENGTH", "extension", 857, "/segments/image[0]/IXSHD/tre[1]/CETAG"),
        ),
    ],
)
def test_tre_framing_refusals(octets, expected):
    assert refusal(_one_tre(octets)) == expected


def test_tags_keep_their_six_octets_and_empty_data_is_allowed():
    found = parse(_one_tre(tre(b" AB CD", b"") + tre(b"ZZZZZZ", b"x")))
    assert [(t.tag, t.slice, t.data) for t in found.extensions] == [
        (" AB CD", nc.Slice(846, 11), nc.Slice(857, 0)),
        ("ZZZZZZ", nc.Slice(857, 12), nc.Slice(868, 1)),
    ]


def test_extension_records_hold_slices_only():
    assert [f.name for f in dataclasses.fields(nc.Extension)] == [
        "section",
        "owner_kind",
        "owner_index",
        "ordinal",
        "origin",
        "des_index",
        "tag",
        "slice",
        "data",
    ]
    found = parse(kit("unknown_duplicate_tre.ntf"))
    for record in found.extensions:
        assert all(
            not isinstance(getattr(record, f.name), (bytes, bytearray))
            for f in dataclasses.fields(record)
        )


# =========================================================================== REQ-032: no TRE semantics


def test_familiar_tags_parse_exactly_like_unknown_ones():
    junk = b"\xff\x00GARBAGE" * 3

    def build(tags):
        return _one_tre(b"".join(tre(tag, junk) for tag in tags))

    familiar = parse(build([b"BLOCKA", b"RPC00A", b"RPC00B"]))
    unknown = parse(build([b"ZZZZZA", b"ZZZZZB", b"ZZZZZC"]))
    assert [t.tag for t in familiar.extensions] == ["BLOCKA", "RPC00A", "RPC00B"]
    assert [dataclasses.replace(t, tag="") for t in familiar.extensions] == [
        dataclasses.replace(t, tag="") for t in unknown.extensions
    ]
    assert familiar.diagnostics == unknown.diagnostics == ()
    unchanged = ("udid", "ixshd", "segment", "fields")
    for one, other in zip(familiar.images, unknown.images):
        for spec in dataclasses.fields(one):
            if spec.name not in unchanged:
                assert getattr(one, spec.name) == getattr(other, spec.name), spec.name
    assert familiar.images[0].fields == unknown.images[0].fields


# =========================================================================== REQ-031: overflow

# The overflow layout: one image whose IXSHD holds two local TREs and names DES 1, and that DES,
# TRE_OVERFLOW for IXSHD of image 1, holding two continuation TREs. HL 417; IXSHDL 851; IXSOFL
# 856; local TREs 859 (13 octets) and 872 (11); the image data 883; the DES subheader 887 (209
# octets: DESOFLW 1083, DESITEM 1089); its data 1096 (TREs 1096, 14 octets, and 1110, 11); FL 1121.
LOCAL = tre(b"LOCAL1", b"ab") + tre(b"LOCAL2", b"")
CONTINUATION = tre(b"CONT01", b"xyz") + tre(b"CONT02", b"")


def overflow_layout(
    overflow=b"001",
    des_subheader=None,
    payload=CONTINUATION,
    images=None,
    extra_des=(),
):
    image = image_sh(IXSHD=area(LOCAL, overflow=overflow))
    return container(
        images=images or [(image, PIXELS)],
        des=[(des_subheader or overflow_des_sh(), payload), *extra_des],
    )


def test_continuation_tres_follow_the_local_ones():
    found = parse(overflow_layout())
    assert found.extensions == (
        nc.Extension(
            "IXSHD", "image", 0, 0, "local", None, "LOCAL1", nc.Slice(859, 13), nc.Slice(870, 2)
        ),
        nc.Extension(
            "IXSHD", "image", 0, 1, "local", None, "LOCAL2", nc.Slice(872, 11), nc.Slice(883, 0)
        ),
        nc.Extension(
            "IXSHD", "image", 0, 2, "overflow", 0, "CONT01", nc.Slice(1096, 14), nc.Slice(1107, 3)
        ),
        nc.Extension(
            "IXSHD", "image", 0, 3, "overflow", 0, "CONT02", nc.Slice(1110, 11), nc.Slice(1121, 0)
        ),
    )
    des = found.des[0]
    assert (des.desid, des.desoflw, des.desitem) == ("TRE_OVERFLOW", "IXSHD", 1)
    assert des.fields["DESOFLW"] == nc.Slice(1083, 6) and des.fields["DESITEM"] == nc.Slice(1089, 3)
    assert found.images[0].ixshd.overflow == 1
    assert found.metadata_bytes == 417 + 466 + 209 + 25


OFL = ("E_OVERFLOW", "extension", 856, "/segments/image[0]/IXSOFL")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (overflow_layout(overflow=b"002"), OFL),
        (overflow_layout(des_subheader=des_sh(DESID=_a("OTHER", 25))), OFL),
        (overflow_layout(des_subheader=overflow_des_sh(section="UDID")), OFL),
        (overflow_layout(des_subheader=overflow_des_sh(item=2)), OFL),
        (overflow_layout(des_subheader=overflow_des_sh(item=0)), OFL),
        (
            container(images=[(image_sh(IXSHD=area(LOCAL, overflow=b"001")), PIXELS)]),
            ("E_OVERFLOW", "extension", 843, "/segments/image[0]/IXSOFL"),
        ),
        (overflow_layout(overflow=b"000"), ("E_OVERFLOW", "extension", 887, "/segments/des[0]")),
        (
            overflow_layout(payload=tre(b"CONT01", b"xyz", cel=b"0000X")),
            ("E_OVERFLOW", "extension", 1102, "/segments/des[0]/data/tre[0]/CEL"),
        ),
        (
            overflow_layout(payload=tre(b"CONT01", b"xyz", cel=b"00099")),
            ("E_OVERFLOW", "extension", 1107, "/segments/des[0]/data/tre[0]/CEDATA"),
        ),
        (
            overflow_layout(payload=tre(b"cont01", b"xyz")),
            ("E_OVERFLOW", "extension", 1096, "/segments/des[0]/data/tre[0]/CETAG"),
        ),
        (
            overflow_layout(payload=tre(b"CONT01", b"xyz") + b"AB"),
            ("E_OVERFLOW", "extension", 1110, "/segments/des[0]/data/tre[1]/CETAG"),
        ),
        (
            # A second TRE_OVERFLOW DES nobody names: one more directory entry moves HL to 430,
            # so DES 0 sits at 900 (209 + 25 octets) and DES 1 at 1134.
            overflow_layout(extra_des=[(overflow_des_sh(), CONTINUATION)]),
            ("E_OVERFLOW", "extension", 1134, "/segments/des[1]"),
        ),
    ],
    ids=[
        "dangling",
        "not-tre-overflow",
        "wrong-section",
        "wrong-item",
        "file-item-for-a-segment",
        "no-des",
        "orphan",
        "payload-cel-digits",
        "payload-cedata-crosses",
        "payload-tag",
        "payload-fragment",
        "second-orphan",
    ],
)
def test_every_overflow_association_fault_is_refused(raw, expected):
    assert refusal(raw) == expected


def test_a_des_named_by_two_areas_is_refused_at_the_later_area():
    # Two images naming DES 1: the second area's reference fails at its own overflow field.
    first = image_sh(IXSHD=area(LOCAL, overflow=b"001"))
    second = image_sh(IXSHD=area(b"", overflow=b"001"))
    raw = container(
        images=[(first, PIXELS), (second, PIXELS)], des=[(overflow_des_sh(), CONTINUATION)]
    )
    # HL 433; image 0 at 433 (466 + 4), image 1 at 903: IXSHDL 1337, IXSOFL 1342.
    assert refusal(raw) == ("E_OVERFLOW", "extension", 1342, "/segments/image[1]/IXSOFL")


def test_file_and_second_image_areas_resolve_by_their_own_item():
    raw = container(
        udhd=area(b"", overflow=b"001"), des=[(overflow_des_sh("UDHD", 0), CONTINUATION)]
    )
    found = parse(raw)
    assert [
        (t.section, t.owner_kind, t.owner_index, t.ordinal, t.origin, t.des_index)
        for t in found.extensions
    ] == [
        ("UDHD", "file", None, 0, "overflow", 0),
        ("UDHD", "file", None, 1, "overflow", 0),
    ]
    # UDHDL at 407 (HL 420): its overflow number at 412.
    wrong = container(
        udhd=area(b"", overflow=b"001"), des=[(overflow_des_sh("UDHD", 1), CONTINUATION)]
    )
    assert refusal(wrong) == ("E_OVERFLOW", "extension", 412, "/file_header/UDHOFL")
    images = [
        (image_sh(), PIXELS),
        (image_sh(UDID=area(b"", overflow=b"001"), IDLVL=b"002"), PIXELS),
    ]
    found = parse(container(images=images, des=[(overflow_des_sh("UDID", 2), CONTINUATION)]))
    assert [(t.section, t.owner_index, t.origin) for t in found.extensions] == [
        ("UDID", 1, "overflow"),
        ("UDID", 1, "overflow"),
    ]


@pytest.mark.parametrize(
    "section, build, ofl",
    [
        # XHD: HL 420, UDHDL 407, XHDL 412, its overflow number 417.
        (
            "XHD",
            lambda des: container(xhd=area(b"", overflow=b"001"), des=des),
            (417, "/file_header/XHDLOFL"),
        ),
        # SXSHD: HL 427, image 427 (data 866), graphic 870, SXSHDL 1123, SXSOFL 1128.
        (
            "SXSHD",
            lambda des: container(
                graphics=[(graphic_sh(SXSHD=area(b"", overflow=b"001")), b"")], des=des
            ),
            (1128, "/segments/graphic[0]/SXSOFL"),
        ),
        # TXSHD: HL 426, image 426 (data 865), text 869, TXSHDL 1146, TXSOFL 1151.
        (
            "TXSHD",
            lambda des: container(
                texts=[(text_sh(TXSHD=area(b"", overflow=b"001")), b"HELLO")], des=des
            ),
            (1151, "/segments/text[0]/TXSOFL"),
        ),
    ],
)
def test_the_header_graphic_and_text_areas_resolve_their_overflow(section, build, ofl):
    owner_kind, owner_index, item = {
        "XHD": ("file", None, 0),
        "SXSHD": ("graphic", 0, 1),
        "TXSHD": ("text", 0, 1),
    }[section]
    found = parse(build([(overflow_des_sh(section, item), CONTINUATION)]))
    assert [
        (t.section, t.owner_kind, t.owner_index, t.ordinal, t.origin, t.des_index, t.tag)
        for t in found.extensions
    ] == [
        (section, owner_kind, owner_index, 0, "overflow", 0, "CONT01"),
        (section, owner_kind, owner_index, 1, "overflow", 0, "CONT02"),
    ]
    assert refusal(build([(overflow_des_sh(section, item + 1), CONTINUATION)])) == (
        "E_OVERFLOW",
        "extension",
        *ofl,
    )


def test_an_overflow_payload_is_framed_once_and_never_chased():
    found = parse(
        overflow_layout(payload=tre(b"CONT01", b"00001001") + tre(b"CONT02", area(b"", b"001")))
    )
    assert [t.tag for t in found.extensions] == ["LOCAL1", "LOCAL2", "CONT01", "CONT02"]


def test_the_overflow_payload_is_charged_once_and_counted_with_the_tres():
    total = 417 + 466 + 209 + 25
    assert parse(overflow_layout(), nc.Limits(metadata_bytes=total)).metadata_bytes == total
    assert refusal(overflow_layout(), nc.Limits(metadata_bytes=total - 1)) == (
        "E_LIMIT",
        "extension",
        856,
        "/segments/image[0]/IXSOFL",
    )
    assert refusal(overflow_layout(), nc.Limits(tre_count=2)) == (
        "E_LIMIT",
        "extension",
        1096,
        "/segments/des[0]/data/tre[0]",
    )
    assert len(parse(overflow_layout(), nc.Limits(tre_count=4)).extensions) == 4


# =========================================================================== REQ-033 / REQ-034: images


def test_comments_zero_and_nine():
    nine = image_sh(NICOM=b"9", ICOM=b"".join(_a(f"COMMENT {k}", 80) for k in range(9)))
    image = parse(container(images=[(nine, PIXELS)])).images[0]
    assert image.nicom == 9
    assert [image.fields[f"ICOM[{k}]"] for k in range(9)] == [
        nc.Slice(777 + 80 * k, 80) for k in range(9)
    ]
    assert image.fields["IC"] == nc.Slice(1497, 2)
    assert parse(container()).images[0].nicom == 0


def test_comrat_is_present_exactly_when_ic_is_not_nc_or_nm():
    image = parse(container(images=[(image_sh(IC=b"C8", COMRAT=b"N045"), PIXELS)])).images[0]
    assert image.comrat == nc.Slice(779, 4) and image.fields["NBANDS"] == nc.Slice(783, 1)
    assert parse(container(images=[(image_sh(IC=b"NM"), PIXELS)])).images[0].comrat is None
    assert parse(container()).images[0].comrat is None
    assert refusal(container(images=[(image_sh(COMRAT=b"N045"), PIXELS)])) == (
        "E_DIGITS",
        "segment",
        779,
        "/segments/image[0]/NBANDS",
    )


def _bands(count: int) -> bytes:
    return BAND * count


def test_band_counts():
    nine = parse(container(images=[(image_sh(NBANDS=b"9", BANDS=_bands(9)), PIXELS * 9)])).images[0]
    assert nine.band_count == 9 and [b.index for b in nine.bands] == list(range(9))
    ten = image_sh(NBANDS=b"0", XBANDS=b"00010", BANDS=_bands(10))
    image = parse(container(images=[(ten, PIXELS * 10)])).images[0]
    assert image.band_count == 10 and image.fields["XBANDS"] == nc.Slice(780, 5)
    assert image.bands[9].irepband == "M" and image.bands[9].lut is None
    zero = image_sh(NBANDS=b"0", XBANDS=b"00000", BANDS=b"")
    assert refusal(container(images=[(zero, PIXELS)])) == (
        "E_FIELD",
        "segment",
        780,
        "/segments/image[0]/XBANDS",
    )


def test_the_band_cap_on_the_wire():
    most = image_sh(NBANDS=b"0", XBANDS=b"00256", BANDS=_bands(256))
    assert parse(container(images=[(most, PIXELS * 256)])).images[0].band_count == 256
    over = image_sh(NBANDS=b"0", XBANDS=b"00257", BANDS=_bands(257))
    assert refusal(container(images=[(over, PIXELS * 257)])) == (
        "E_LIMIT",
        "segment",
        780,
        "/segments/image[0]/XBANDS",
    )
    assert refusal(
        container(images=[(image_sh(NBANDS=b"2", BANDS=_bands(2)), PIXELS * 2)]), nc.Limits(bands=1)
    ) == (
        "E_LIMIT",
        "segment",
        779,
        "/segments/image[0]/NBANDS",
    )


def test_luts_are_kept_as_slices():
    lut = b"\x00\x10\x20\x30\x01\x11\x21\x31\x02\x12\x22\x32"
    band = b"LU" + b" " * 6 + b"N" + b" " * 3 + b"3" + b"00004" + lut
    image = parse(container(images=[(image_sh(BANDS=band), PIXELS)])).images[0]
    assert image.bands[0] == nc.BandRecord(0, "LU", 3, 4, nc.Slice(798, 12))
    assert image.fields["band[0]/NELUTS"] == nc.Slice(793, 5)
    assert image.fields["band[0]/LUTD"] == nc.Slice(798, 12)
    assert image.fields["ISYNC"] == nc.Slice(810, 1)
    empty = b"LU" + b" " * 6 + b"N" + b" " * 3 + b"1" + b"00000"
    assert parse(container(images=[(image_sh(BANDS=empty), PIXELS)])).images[0].bands[
        0
    ].lut == nc.Slice(798, 0)


def test_the_lut_cap_by_injection():
    assert 9 * 99_999 < nc.Limits().lut_bytes
    two_by_four = b"LU" + b" " * 6 + b"N" + b" " * 3 + b"2" + b"00004" + bytes(8)
    assert parse(container(images=[(image_sh(BANDS=two_by_four), PIXELS)]), nc.Limits(lut_bytes=8))
    three_by_three = b"LU" + b" " * 6 + b"N" + b" " * 3 + b"3" + b"00003" + bytes(9)
    assert refusal(
        container(images=[(image_sh(BANDS=three_by_three), PIXELS)]), nc.Limits(lut_bytes=8)
    ) == (
        "E_LIMIT",
        "segment",
        793,
        "/segments/image[0]/band[0]/NELUTS",
    )


def test_encryption_and_exact_consumption_of_an_image_subheader():
    mono = kit("mono_nsif101.ntf")
    assert refusal(put(mono, 694, b"1")) == (
        "E_ENCRYPTED",
        "segment",
        694,
        "/segments/image[0]/ENCRYP",
    )
    assert refusal(put(mono, 694, b"X")) == ("E_FIELD", "segment", 694, "/segments/image[0]/ENCRYP")
    assert refusal(container(images=[(image_sh() + b" ", PIXELS)])) == (
        "E_LENGTH",
        "segment",
        843,
        "/segments/image[0]",
    )


def _grid(**over):
    return container(images=[(image_sh(**over), PIXELS)])


@pytest.mark.parametrize(
    "over, expected",
    [
        ({"NROWS": b"00000000"}, ("E_FIELD", "segment", 737, "/segments/image[0]/NROWS")),
        ({"NCOLS": b"00000000"}, ("E_FIELD", "segment", 745, "/segments/image[0]/NCOLS")),
        ({"ABPP": b"00"}, ("E_FIELD", "segment", 772, "/segments/image[0]/ABPP")),
        ({"NBPR": b"0000"}, ("E_FIELD", "segment", 795, "/segments/image[0]/NBPR")),
        ({"NBPC": b"0000"}, ("E_FIELD", "segment", 799, "/segments/image[0]/NBPC")),
        ({"NBPP": b"00"}, ("E_FIELD", "segment", 811, "/segments/image[0]/NBPP")),
        ({"IDLVL": b"000"}, ("E_FIELD", "segment", 813, "/segments/image[0]/IDLVL")),
        ({"ABPP": b"09"}, ("E_FIELD", "segment", 772, "/segments/image[0]/ABPP")),
        ({"PJUST": b"X"}, ("E_FIELD", "segment", 774, "/segments/image[0]/PJUST")),
        ({"PJUST": b"l"}, ("E_FIELD", "segment", 774, "/segments/image[0]/PJUST")),
        ({"IMODE": b"X"}, ("E_FIELD", "segment", 794, "/segments/image[0]/IMODE")),
        (
            {"NBPR": b"0002", "NPPBH": b"0000"},
            ("E_FIELD", "segment", 803, "/segments/image[0]/NPPBH"),
        ),
        (
            {"NBPC": b"0002", "NPPBV": b"0000"},
            ("E_FIELD", "segment", 807, "/segments/image[0]/NPPBV"),
        ),
        ({"NPPBH": b"0001"}, ("E_FIELD", "segment", 795, "/segments/image[0]/NBPR")),
        ({"NPPBV": b"0001"}, ("E_FIELD", "segment", 799, "/segments/image[0]/NBPC")),
        ({"NBPR": b"0002"}, ("E_PROFILE", "segment", 795, "/segments/image[0]/NBPR")),
        ({"NBPC": b"0002"}, ("E_PROFILE", "segment", 799, "/segments/image[0]/NBPC")),
        (
            {"NBPR": b"0003", "NPPBH": b"0001"},
            ("E_PROFILE", "segment", 795, "/segments/image[0]/NBPR"),
        ),
        ({"NROWS": b"01000001"}, ("E_LIMIT", "segment", 737, "/segments/image[0]/NROWS")),
        ({"NCOLS": b"01000001"}, ("E_LIMIT", "segment", 745, "/segments/image[0]/NCOLS")),
    ],
)
def test_every_image_relation_refuses_at_its_field(over, expected):
    assert refusal(_grid(**over)) == expected


def test_zero_block_sizes_mean_one_block_spanning_the_axis():
    image = parse(_grid(NPPBH=b"0000", NPPBV=b"0000")).images[0]
    assert (image.nppbh, image.nppbv, image.block_width, image.block_height) == (0, 0, 2, 2)
    raw = container(
        images=[
            (
                image_sh(
                    NROWS=b"00000003", NCOLS=b"00000005", NPPBH=b"0000", NPPBV=b"0002", NBPC=b"0002"
                ),
                bytes(20),
            )
        ]
    )
    image = parse(raw).images[0]
    assert (image.nbpr, image.nbpc, image.block_width, image.block_height) == (1, 2, 5, 2)
    padded = image_sh(NROWS=b"00000003", NCOLS=b"00000005", NPPBH=b"0008", NPPBV=b"0004")
    image = parse(container(images=[(padded, bytes(32))])).images[0]
    assert (image.block_width, image.block_height, image.segment.data.length) == (8, 4, 32)


def test_the_dimension_and_block_caps_on_the_wire():
    tall = image_sh(NROWS=b"01000000", NPPBV=b"0000", PVTYPE=b"R  ", ABPP=b"32", NBPP=b"32")
    assert parse(container(images=[(tall, b"")])).images[0].nrows == 1_000_000
    grid = dict(NROWS=b"00000256", NPPBV=b"0001", NBPC=b"0256", NPPBH=b"0001")
    most = image_sh(NCOLS=b"00000256", NBPR=b"0256", **grid)
    assert parse(container(images=[(most, bytes(65_536))])).images[0].nbpr == 256
    over = image_sh(NCOLS=b"00000257", NBPR=b"0257", **grid)
    assert refusal(container(images=[(over, bytes(65_792))])) == (
        "E_LIMIT",
        "segment",
        795,
        "/segments/image[0]/NBPR",
    )


# =========================================================================== REQ-035: codes


@pytest.mark.parametrize("icords", [b"U", b"N", b"S", b"C", b"X", b"G", b"D"])
def test_a_non_blank_icords_consumes_igeolo_whatever_it_means(icords):
    image = image_sh(ICORDS=icords, IGEOLO=b"\xff" * 30 + b"A" * 30)
    found = parse(container(images=[(image, PIXELS)]))
    record = found.images[0]
    assert (record.icords, record.igeolo, record.fields["NICOM"]) == (
        icords.decode(),
        nc.Slice(776, 60),
        nc.Slice(836, 1),
    )
    # Geometry is not read here; nothing else about the image is changed by the corners.
    assert [d for d in diagnostics(found) if d[1] != "geometry"] == []


def test_blank_icords_reads_no_igeolo():
    raw = put(kit("geo_dms.ntf"), 775, b" ")
    assert refusal(raw) == ("E_LENGTH", "segment", 857, "/segments/image[0]/ICOM[1]")


@pytest.mark.parametrize(
    "ic", ["NM", "C1", "M1", "C3", "M3", "C4", "M4", "C5", "M5", "C8", "M8", "ZZ", "A9"]
)
def test_every_named_and_unknown_compression_code_is_inventoried_without_a_pixel_path(ic):
    comrat = b"" if ic == "NM" else b"1.0 "
    found = parse(
        container(
            images=[(image_sh(IC=ic.encode(), COMRAT=comrat), b"\x01\x02\x03\x04\x05\x06\x07")]
        )
    )
    image = found.images[0]
    if ic in ("ZZ", "A9"):
        code, reason, message = (
            "UNSUPPORTED_COMPRESSION",
            "unsupported_compression",
            "compression code is not one this profile names",
        )
    else:
        code, reason, message = (
            "COMPRESSION_NOT_ENABLED",
            "compression_not_enabled",
            "no pixel path is enabled for this compression code in this deployment",
        )
    assert (image.pixel_status, image.pixel_reason, image.ic) == ("unsupported", reason, ic)
    assert found.diagnostics == (
        nc.Diagnostic(code, "pixels", 777, "/segments/image[0]/IC", message),
    )
    assert nc.DIAGNOSTIC_CODES[code] is False


@pytest.mark.parametrize("ic", [b"nc", b"N-", b"  ", b"N\x00"])
def test_an_ic_outside_the_two_character_syntax_is_refused(ic):
    assert refusal(container(images=[(image_sh(IC=ic, COMRAT=b"1.0 "), PIXELS)])) == (
        "E_FIELD",
        "segment",
        777,
        "/segments/image[0]/IC",
    )


@pytest.mark.parametrize(
    "over, reason, code, offset, field, message",
    [
        (
            {"PVTYPE": b"R  ", "ABPP": b"32", "NBPP": b"32"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            753,
            "PVTYPE",
            "no native sample path for this sample type",
        ),
        (
            {"PVTYPE": b"B  ", "ABPP": b"01", "NBPP": b"01"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            753,
            "PVTYPE",
            "no native sample path for this sample type",
        ),
        (
            {"PVTYPE": b"int"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            753,
            "PVTYPE",
            "no native sample path for this sample type",
        ),
        (
            {"PVTYPE": b" SI"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            753,
            "PVTYPE",
            "no native sample path for this sample type",
        ),
        (
            {"ABPP": b"12", "NBPP": b"12"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            811,
            "NBPP",
            "no native sample path for this sample type",
        ),
        (
            {"ABPP": b"32", "NBPP": b"32"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            811,
            "NBPP",
            "no native sample path for this sample type",
        ),
        (
            {"IMODE": b"S"},
            "unsupported_sample_layout",
            "UNSUPPORTED_SAMPLE_LAYOUT",
            794,
            "IMODE",
            "IMODE S needs at least two bands and two blocks in this profile",
        ),
        (
            {"IMODE": b"S", "NBANDS": b"2", "BANDS": BAND * 2},
            "unsupported_sample_layout",
            "UNSUPPORTED_SAMPLE_LAYOUT",
            794,
            "IMODE",
            "IMODE S needs at least two bands and two blocks in this profile",
        ),
    ],
)
def test_the_pixel_cells_outside_the_native_profile(over, reason, code, offset, field, message):
    shifted = offset + (13 if field != "PVTYPE" and "BANDS" in over else 0)
    found = parse(container(images=[(image_sh(**over), b"\x00")]))
    image = found.images[0]
    assert (image.pixel_status, image.pixel_reason) == ("unsupported", reason)
    assert found.diagnostics == (
        nc.Diagnostic(code, "pixels", shifted, f"/segments/image[0]/{field}", message),
    )


def test_imode_s_with_two_bands_and_two_blocks_is_native():
    over = dict(IMODE=b"S", NBANDS=b"2", BANDS=BAND * 2, NBPR=b"0002", NPPBH=b"0001")
    image = parse(container(images=[(image_sh(**over), bytes(8))])).images[0]
    assert (image.pixel_status, image.pixel_reason) == ("native_supported", None)


def test_no_metadata_path_reads_a_sample_octet():
    mode_b = kit("mode_B.ntf")
    flipped = mode_b[:869] + bytes(o ^ 0x5A for o in mode_b[869:])
    assert len(mode_b) == 917
    one, other = parse(mode_b), parse(flipped)
    assert dataclasses.replace(one, raw=b"") == dataclasses.replace(other, raw=b"")
    text = kit("image_and_text.ntf")
    changed = text[:1138] + b"x" * 39
    assert dataclasses.replace(parse(text), raw=b"") == dataclasses.replace(parse(changed), raw=b"")


# =========================================================================== REQ-036: levels


@pytest.mark.parametrize(
    "octets, row, column",
    [
        (b"0000000000", 0, 0),
        (b"-0001-0002", -1, -2),
        (b"00010-0005", 10, -5),
        (b"9999999999", 99999, 99999),
    ],
)
def test_iloc_is_row_then_column_read_tolerantly(octets, row, column):
    found = parse(put(kit("mono_nsif101.ntf"), 819, octets))
    assert found.images[0].iloc == nc.Location(nc.Slice(819, 10), row, column)
    assert found.diagnostics == ()


@pytest.mark.parametrize(
    "octets",
    [
        b"+0001 0002",
        b"00001+0002",
        b"0000 00000",
        b"--00100002",
        b"\x00" * 10,
        b"-000X-0001",
        b"-0001-000X",
    ],
)
def test_an_uninterpretable_location_is_kept_with_a_diagnostic(octets):
    found = parse(put(kit("mono_nsif101.ntf"), 819, octets))
    assert found.images[0].iloc == nc.Location(nc.Slice(819, 10), None, None)
    assert diagnostics(found) == [
        ("LOCATION_UNINTERPRETED", "segment", 819, "/segments/image[0]/ILOC")
    ]
    assert nc.DIAGNOSTIC_CODES["LOCATION_UNINTERPRETED"] is False


def _with_graphics(*levels, image_levels=(b"001", b"000")):
    image = image_sh(IDLVL=image_levels[0], IALVL=image_levels[1])
    graphics = [(graphic_sh(SDLVL=level, SALVL=parent), b"") for level, parent in levels]
    return container(images=[(image, PIXELS)], graphics=graphics)


def test_composition_is_segment_only_when_every_level_resolves():
    found = parse(_with_graphics((b"002", b"001")))
    assert found.composition_status == "segment_only" and found.diagnostics == ()
    assert (found.graphics[0].sdlvl, found.graphics[0].salvl, found.images[0].ialvl) == (2, 1, 0)


# One graphic: HL 414, image 414, graphic 857 (SDLVL 1071, SALVL 1074), image IALVL 826. Two
# graphics: HL 424, graphic 0 at 867 (SALVL 1084). Four graphics: HL 444, graphics at 887, 1145,
# 1403 and 1661 (SALVL 1104, 1362, 1620 and 1878).
@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            _with_graphics((b"001", b"000")),
            [("COMPOSITION_DUPLICATE_LEVEL", "segment", 1071, "/segments/graphic[0]/SDLVL")],
        ),
        (
            _with_graphics((b"002", b"007")),
            [("COMPOSITION_MISSING_PARENT", "segment", 1074, "/segments/graphic[0]/SALVL")],
        ),
        (
            _with_graphics((b"002", b"002")),
            [("COMPOSITION_CYCLE", "segment", 1074, "/segments/graphic[0]/SALVL")],
        ),
        (
            _with_graphics((b"002", b"001"), image_levels=(b"001", b"002")),
            [("COMPOSITION_CYCLE", "segment", 826, "/segments/image[0]/IALVL")],
        ),
        (
            _with_graphics((b"002", b"003"), (b"003", b"002"), image_levels=(b"001", b"002")),
            [("COMPOSITION_CYCLE", "segment", 1084, "/segments/graphic[0]/SALVL")],
        ),
        (
            # The image (level 1) enters the cycle 2 -> 3 -> 2 at graphic[1]; graphic[0] is the
            # cycle's first member in file order and carries the report.
            _with_graphics((b"003", b"002"), (b"002", b"003"), image_levels=(b"001", b"002")),
            [("COMPOSITION_CYCLE", "segment", 1084, "/segments/graphic[0]/SALVL")],
        ),
        (
            # A later duplicate of level 1 that would attach to itself: the level stays the
            # image's, so there is no cycle.
            _with_graphics((b"001", b"001")),
            [("COMPOSITION_DUPLICATE_LEVEL", "segment", 1071, "/segments/graphic[0]/SDLVL")],
        ),
        (
            _with_graphics((b"002", b"003"), (b"003", b"004"), (b"004", b"002"), (b"005", b"005")),
            [
                ("COMPOSITION_CYCLE", "segment", 1104, "/segments/graphic[0]/SALVL"),
                ("COMPOSITION_CYCLE", "segment", 1878, "/segments/graphic[3]/SALVL"),
            ],
        ),
    ],
    ids=[
        "duplicate",
        "missing-parent",
        "self-attachment",
        "two-member-cycle",
        "tail",
        "tail-entering-a-later-member",
        "later-duplicate-with-another-parent",
        "two-cycles",
    ],
)
def test_composition_faults_leave_the_container_valid(raw, expected):
    found = parse(raw)
    assert diagnostics(found) == expected
    assert found.composition_status == "unavailable"
    assert found.images[0].pixel_status == "native_supported"
    assert all(nc.DIAGNOSTIC_CODES[code] for code, *_ in expected)


def test_a_zero_display_level_is_fatal():
    assert refusal(_with_graphics((b"000", b"000"))) == (
        "E_FIELD",
        "segment",
        1071,
        "/segments/graphic[0]/SDLVL",
    )
    assert refusal(put(kit("mono_nsif101.ntf"), 813, b"000")) == (
        "E_FIELD",
        "segment",
        813,
        "/segments/image[0]/IDLVL",
    )


# =========================================================================== REQ-037: graphics


def test_a_graphic_segment_is_parsed_in_order_and_its_data_is_a_slice():
    graphic = parse(l5(graphics=[(graphic_sh(SLOC=b"-0001-0001"), b"CGM")])).graphics[0]
    assert (graphic.sfmt, graphic.sdlvl, graphic.salvl, graphic.scolor) == ("C", 2, 1, "C")
    assert graphic.sloc == nc.Location(nc.Slice(1110, 10), -1, -1)
    assert graphic.sbnd1 == nc.Location(nc.Slice(1120, 10), 0, 0)
    assert graphic.sbnd2 == nc.Location(nc.Slice(1131, 10), 1, 1)
    assert graphic.sxshd.section == "SXSHD" and graphic.sxshd.length_field == nc.Slice(1143, 5)
    assert graphic.segment.data == nc.Slice(1148, 3)
    assert (graphic.security.scope, graphic.security.prefix, graphic.security.slice) == (
        "graphic",
        "SS",
        nc.Slice(922, 167),
    )


@pytest.mark.parametrize(
    "over, expected",
    [
        ({"SY": b"XX"}, ("E_FIELD", "segment", 890, "/segments/graphic[0]/SY")),
        ({"ENCRYP": b"1"}, ("E_ENCRYPTED", "segment", 1089, "/segments/graphic[0]/ENCRYP")),
        ({"ENCRYP": b"2"}, ("E_FIELD", "segment", 1089, "/segments/graphic[0]/ENCRYP")),
        ({"SFMT": b"\x00"}, ("E_FIELD", "segment", 1090, "/segments/graphic[0]/SFMT")),
        ({"SCOLOR": b"\x7f"}, ("E_FIELD", "segment", 1130, "/segments/graphic[0]/SCOLOR")),
        ({"SDLVL": b"000"}, ("E_FIELD", "segment", 1104, "/segments/graphic[0]/SDLVL")),
        ({"SDLVL": b"0A1"}, ("E_DIGITS", "segment", 1104, "/segments/graphic[0]/SDLVL")),
        ({"SXSHD": b"00000 "}, ("E_LENGTH", "segment", 1148, "/segments/graphic[0]")),
        ({"SXSHD": b"0000"}, ("E_LENGTH", "extension", 1143, "/segments/graphic[0]/SXSHDL")),
    ],
)
def test_the_graphic_subheader_refusals(over, expected):
    assert refusal(l5(graphics=[(graphic_sh(**over), b"CGM")])) == expected


# =========================================================================== REQ-038: text


def test_a_text_segment_is_kept_with_its_format_and_its_payload_unread():
    found = parse(kit("image_and_text.ntf"))
    text = found.texts[0]
    assert (text.txtfmt, text.txtalvl, text.txtdt.status) == ("STA", 0, "valid")
    assert text.segment.data == nc.Slice(1138, 39)
    assert text.security.prefix == "TS" and text.txshd.length == 0
    payload = found.raw[1138:1177]
    assert payload == b"<script>must remain plain text</script>"
    assert nc.text_displayable(text.txtfmt, payload) is True


@pytest.mark.parametrize(
    "txtfmt, payload, shown",
    [
        ("STA", b"plain text", True),
        ("STA", b"", True),
        ("STA", b"two\r\nlines", False),
        ("STA", b"tab\there", False),
        ("STA", b"\x7f", False),
        ("STA", b"caf\xc3\xa9", False),
        ("UT1", b"plain text", False),
        ("MTF", b"plain text", False),
        ("sta", b"plain text", False),
    ],
)
def test_the_display_predicate(txtfmt, payload, shown):
    assert nc.text_displayable(txtfmt, payload) is shown


def test_the_text_subheader_refusals():
    text = kit("image_and_text.ntf")
    assert refusal(put(text, 856, b"XX")) == ("E_FIELD", "segment", 856, "/segments/text[0]/TE")
    assert refusal(put(text, 1129, b"1")) == (
        "E_ENCRYPTED",
        "segment",
        1129,
        "/segments/text[0]/ENCRYP",
    )
    assert refusal(l5(texts=[(text_sh() + b" ", b"HELLO")])) == (
        "E_LENGTH",
        "segment",
        1433,
        "/segments/text[0]",
    )
    assert refusal(container(texts=[(text_sh() + b" ", b"")])) == (
        "E_LENGTH",
        "segment",
        1138,
        "/segments/text[0]",
    )


# =========================================================================== REQ-039: DES and RES


def test_des_and_res_are_parsed_in_order_and_their_payloads_are_opaque():
    found = parse(l5())
    des, res = found.des[0], found.res[0]
    assert (des.desid, des.desoflw, des.desitem, des.user_subheader) == (
        "SYNTHETIC_DES",
        None,
        None,
        nc.Slice(1638, 0),
    )
    assert (des.security.scope, des.security.prefix) == ("des", "DES")
    assert des.segment.data == nc.Slice(1638, 4)
    assert (res.resid, res.user_subheader, res.security.prefix) == (
        "SYNTHETIC_RES",
        nc.Slice(1842, 0),
        "RE",
    )
    assert res.segment.data == nc.Slice(1842, 2)
    leading = parse(l5(des=[(des_sh(DESID=_a(" TRE_OVERFLOW", 25)), b"DATA")])).des[0]
    assert (leading.desid, leading.desoflw, "DESOFLW" in leading.fields) == (
        " TRE_OVERFLOW",
        None,
        False,
    )


@pytest.mark.parametrize(
    "parts, expected",
    [
        ({"des": [(des_sh() + b" ", b"DATA")]}, ("E_LENGTH", "segment", 1638, "/segments/des[0]")),
        ({"res": [(res_sh() + b" ", b"RS")]}, ("E_LENGTH", "segment", 1842, "/segments/res[0]")),
        (
            {"des": [(des_sh(DESSHL=b"0005", DESSHF=b"ABCD"), b"DATA")]},
            ("E_LENGTH", "segment", 1638, "/segments/des[0]/DESSHF"),
        ),
        (
            {"res": [(res_sh(RESSHL=b"0003", RESSHF=b"AB"), b"RS")]},
            ("E_LENGTH", "segment", 1842, "/segments/res[0]/RESSHF"),
        ),
        (
            {"des": [(des_sh(DE=b"DX"), b"DATA")]},
            ("E_FIELD", "segment", 1438, "/segments/des[0]/DE"),
        ),
        ({"res": [(res_sh(RE=b"ER"), b"RS")]}, ("E_FIELD", "segment", 1642, "/segments/res[0]/RE")),
        (
            {"des": [(des_sh(DESSHL=b"00A0"), b"DATA")]},
            ("E_DIGITS", "segment", 1634, "/segments/des[0]/DESSHL"),
        ),
    ],
)
def test_the_des_and_res_refusals(parts, expected):
    assert refusal(l5(**parts)) == expected


def test_reserved_and_version_fields_are_preserved_raw():
    found = parse(
        l5(des=[(des_sh(DESVER=b"XX"), b"DATA")], res=[(res_sh(RESVER=b"\xff\x00"), b"RS")])
    )
    assert found.des[0].fields["DESVER"] == nc.Slice(1465, 2) and found.diagnostics == ()
    assert found.raw[1669:1671] == b"\xff\x00"


# =========================================================================== REQ-024: security


def test_every_scope_has_its_block_prefix_and_owner():
    found = parse(l5())
    blocks = [
        found.file_header.security,
        found.images[0].security,
        found.graphics[0].security,
        found.texts[0].security,
        found.des[0].security,
        found.res[0].security,
    ]
    assert [(b.scope, b.owner_index, b.prefix, b.slice, b.clas) for b in blocks] == [
        ("file", None, "FS", nc.Slice(119, 167), "U"),
        ("image", 0, "IS", nc.Slice(570, 167), "U"),
        ("graphic", 0, "SS", nc.Slice(922, 167), "U"),
        ("text", 0, "TS", nc.Slice(1257, 167), "U"),
        ("des", 0, "DES", nc.Slice(1467, 167), "U"),
        ("res", 0, "RE", nc.Slice(1671, 167), "U"),
    ]
    relative = [
        (name, s.offset - 1467, s.length) for name, s in found.des[0].security.fields.items()
    ]
    assert relative == [
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
    ]


@pytest.mark.parametrize(
    "octet, clas",
    [
        (b"U", "U"),
        (b"R", "R"),
        (b"C", "C"),
        (b"S", "S"),
        (b"T", "T"),
        (b" ", None),
        (b"X", None),
        (b"u", None),
        (b"\x00", None),
    ],
)
def test_clas_resolves_only_the_five_letters_and_never_defaults(octet, clas):
    found = parse(put(put(kit("mono_nsif101.ntf"), 119, octet), 527, octet))
    assert found.file_header.security.clas == clas and found.images[0].security.clas == clas
    assert found.diagnostics == ()


def test_no_octet_inside_a_present_block_is_an_error():
    raw = put(put(kit("mono_nsif101.ntf"), 222, b"\xff" * 40), 527 + 103, b"\x00\xff" * 20)
    found = parse(raw)
    assert found.file_header.security.fields["CAUT"] == nc.Slice(222, 40)
    assert found.diagnostics == ()


# =========================================================================== REQ-077: atomic, bounded


def test_every_proper_prefix_of_a_vector_is_refused_at_stage_header():
    mono = kit("mono_nsif101.ntf")
    outcomes = set()
    for end in range(len(mono)):
        with pytest.raises(nc.NsifError) as caught:
            nc.parse_container(mono[:end], LIMITS)
        outcomes.add((caught.value.code, caught.value.stage))
    assert outcomes == {("E_LENGTH", "header")}


def test_a_security_block_cut_by_its_structure_is_fatal():
    assert refusal(kit("mono_nsif101.ntf")[:200]) == (
        "E_LENGTH",
        "header",
        119,
        "/file_header/security",
    )
    assert refusal(container(images=[(image_sh()[:250], b"")])) == (
        "E_LENGTH",
        "segment",
        527,
        "/segments/image[0]/security",
    )


def test_a_container_with_unsupported_pixels_keeps_its_inventory():
    found = parse(container(images=[(image_sh(IC=b"C8", COMRAT=b"N045"), b"\xff\xd8\xff\xd9")]))
    assert len(found.images) == 1 and found.images[0].pixel_status == "unsupported"
    assert found.images[0].segment.data == nc.Slice(847, 4)


def test_diagnostics_are_sorted_and_bounded_by_construction():
    image = image_sh(
        IID1=b"\xe9" + b" " * 9,
        IDATIM=b"2026----------",
        IC=b"ZZ",
        COMRAT=b"1.0 ",
        IALVL=b"099",
        ILOC=b"+0001 0002",
    )
    raw = container(images=[(image, b"")] * 64, FDT=b"2026----------", FTITLE=b"\xe9" * 80)
    found = parse(raw)
    # Two for the header, four for every image's own fields, 63 duplicate levels, 64 missing
    # parents: 2 + 256 + 63 + 64.
    assert len(found.diagnostics) == 385 <= 2 + 8 * 64
    assert list(found.diagnostics) == sorted(found.diagnostics, key=nc.diagnostic_sort_key)
    assert found.diagnostics[:2] == (
        nc.Diagnostic(
            "DATE_PARTIAL",
            "header",
            25,
            "/file_header/FDT",
            "the date is a partial value, preserved and not interpreted",
        ),
        nc.Diagnostic(
            "TEXT_UNINTERPRETED",
            "header",
            39,
            "/file_header/FTITLE",
            "descriptive text holds octets outside printable ASCII and is not interpreted",
        ),
    )
    assert found.composition_status == "unavailable"


def test_the_codec_has_no_catch_all_and_constructs_no_host_code():
    tree = ast.parse(CODEC.read_text())
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    assert sorted(ast.unparse(h.type) for h in handlers if h.type is not None) == [
        "ValueError",
        "binascii.Error",
    ]
    assert all(h.type is not None for h in handlers)
    # Every E_ string constant outside the table of all section 19 codes.
    table = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "ERROR_CODES" for t in node.targets
        ):
            table |= {id(inner) for inner in ast.walk(node)}
    codes = {
        node.value
        for node in ast.walk(tree)
        if id(node) not in table
        and isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"E_[A-Z]+", node.value)
    }
    assert codes <= {
        "E_MAGIC",
        "E_PROFILE",
        "E_DIGITS",
        "E_LENGTH",
        "E_FIELD",
        "E_OVERFLOW",
        "E_LIMIT",
        "E_ENCRYPTED",
        "E_CODEC",
        "E_CONTEXT",
    }
    assert "E_LENGTH" in codes


def _tiles(fields, start, end):
    position = start
    for name, part in fields.items():
        assert part.offset == position, name
        position = part.offset + part.length
    assert position == end


@pytest.mark.parametrize("name", [n for n in KIT_OUTCOMES if KIT_OUTCOMES[n][1] == "ok"])
def test_no_source_octet_is_dropped(name):
    found = parse(kit(name))
    _tiles(found.file_header.fields, 0, found.header_length)
    for record in (*found.images, *found.texts):
        _tiles(
            record.fields,
            record.segment.subheader.offset,
            record.segment.subheader.offset + record.segment.subheader.length,
        )
    five = parse(l5())
    for record in (*five.images, *five.graphics, *five.texts, *five.des, *five.res):
        _tiles(
            record.fields,
            record.segment.subheader.offset,
            record.segment.subheader.offset + record.segment.subheader.length,
        )


def _every_slice(found):
    for record in (
        found.file_header,
        *found.images,
        *found.graphics,
        *found.texts,
        *found.des,
        *found.res,
    ):
        yield from record.fields.values()
    for segment in found.segments:
        yield segment.subheader
        yield segment.data
    for extension in found.extensions:
        yield extension.slice
        yield extension.data


def test_single_octet_mutations_give_a_container_or_one_coded_refusal():
    for seed in (l5(), overflow_layout(), kit("unknown_duplicate_tre.ntf")):
        for offset in range(len(seed)):
            for octet in (0x00, 0xFF, 0x30, 0x39, 0x20, 0x2D):
                mutated = seed[:offset] + bytes((octet,)) + seed[offset + 1 :]
                try:
                    found = nc.parse_container(mutated, LIMITS)
                except nc.NsifError as error:
                    assert error.offset is None or 0 <= error.offset <= len(mutated)
                    continue
                for part in _every_slice(found):
                    assert 0 <= part.offset <= part.offset + part.length <= found.file_size


# =========================================================================== REQ-013: the error model


def test_an_error_renders_code_offset_path_and_explanation():
    error = nc.NsifError("E_LENGTH", "header", 342, "/file_header/FL", "x")
    assert str(error) == error.args[0] == "E_LENGTH @byte 342 /file_header/FL: x"
    assert str(nc.NsifError("E_FIELD", "input", None, "/twin", "y")) == "E_FIELD @byte - /twin: y"
    assert isinstance(error, ValueError) and not isinstance(error, (InputTooLarge, InputTooDeep))
    assert not issubclass(nc.NsifError, (InputTooLarge, InputTooDeep))
    assert issubclass(nc.NsifInputTooLarge, nc.NsifError) and issubclass(
        nc.NsifInputTooLarge, InputTooLarge
    )
    assert issubclass(nc.NsifInputTooDeep, nc.NsifError) and issubclass(
        nc.NsifInputTooDeep, InputTooDeep
    )
    for name in KIT_OUTCOMES:
        if KIT_OUTCOMES[name][1] != "ok":
            with pytest.raises(nc.NsifError) as caught:
                parse(kit(name))
            assert "/field/" not in str(caught.value)


@pytest.mark.parametrize(
    "arguments",
    [
        ("E_FIELD", "policy", 0, "/x", "y"),
        ("E_NOPE", "header", 0, "/x", "y"),
        ("E_FIELD", "header", -1, "/x", "y"),
        ("E_FIELD", "header", True, "/x", "y"),
        ("E_FIELD", "header", 1.0, "/x", "y"),
        ("E_FIELD", "header", 0, "x", "y"),
        ("E_FIELD", "header", 0, "/x", None),
    ],
)
def test_an_error_refuses_anything_outside_its_vocabulary(arguments):
    with pytest.raises(TypeError):
        nc.NsifError(*arguments)


@pytest.mark.parametrize(
    "error",
    [
        nc.NsifError("E_OVERFLOW", "extension", 856, "/segments/image[0]/IXSOFL", "z"),
        nc.NsifInputTooLarge("/input", "input is 9 octets; the limit is 8"),
        nc.NsifInputTooLarge("/twin/wire_b64", "another path"),
        nc.NsifInputTooDeep("/twin", "twin nests deeper than 4 containers"),
    ],
)
def test_an_error_pickles_and_copies_unchanged(error):
    for copied in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
        assert type(copied) is type(error)
        assert (copied.code, copied.stage, copied.offset, copied.path, copied.explanation) == (
            error.code,
            error.stage,
            error.offset,
            error.path,
            error.explanation,
        )
        assert str(copied) == str(error) and copied.args == error.args


def test_no_error_string_carries_a_source_value():
    secret_tre = tre(b"SECRET", b"SECRETXYZ")
    planted = container(
        images=[(image_sh(IXSHD=area(secret_tre)), PIXELS)],
        OSTAID=_a("SECRETXYZ", 10),
        FTITLE=_a("SECRETXYZ", 80),
    )
    failures = [
        planted[:-1],
        container(
            images=[(image_sh(IXSHD=area(tre(b"SECRET", b"SECRETXYZ", cel=b"00099"))), PIXELS)],
            OSTAID=_a("SECRETXYZ", 10),
        ),
        container(
            images=[(image_sh(IXSHD=area(tre(b"SECRET", b"SECRETXYZ", cel=b"SECRE"))), PIXELS)]
        ),
        put(planted, 39, b"\xe9SECRETXYZ"),
    ]
    for raw in failures[:3]:
        with pytest.raises(nc.NsifError) as caught:
            parse(raw)
        assert "SECRET" not in str(caught.value) and "SECRE" not in caught.value.path
    found = parse(failures[3])
    assert diagnostics(found) == [("TEXT_UNINTERPRETED", "header", 39, "/file_header/FTITLE")]
    assert all("SECRET" not in str(d) for d in found.diagnostics)


#: The diagnostic registry, copied: code -> listed by validate_source as a profile violation.
REGISTRY = {
    "DATE_UNKNOWN": False,
    "DATE_PARTIAL": False,
    "TIME_UNRESOLVED": False,
    "DATE_MALFORMED": True,
    "TEXT_UNINTERPRETED": False,
    "LOCATION_UNINTERPRETED": False,
    "COMPOSITION_DUPLICATE_LEVEL": True,
    "COMPOSITION_MISSING_PARENT": True,
    "COMPOSITION_CYCLE": True,
    "UNSUPPORTED_SAMPLE_TYPE": False,
    "UNSUPPORTED_SAMPLE_LAYOUT": False,
    "COMPRESSION_NOT_ENABLED": False,
    "UNSUPPORTED_COMPRESSION": False,
    "GEOMETRY_INVALID": True,
    "GEOMETRY_UNRESOLVED": False,
    "GEOMETRY_UNSUPPORTED": False,
    "FILL_BITS_NONZERO": False,
    "FILL_BITS_SIGN_EXTENDED": False,
    "COLOUR_INTERPRETATION_UNRESOLVED": False,
}


def test_the_diagnostic_registry():
    assert dict(nc.DIAGNOSTIC_CODES) == REGISTRY
    assert all(
        re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code) and not code.startswith("E_")
        for code in REGISTRY
    )
    assert {
        "POLICY_ASSESSMENT_INCOMPLETE",
        "ORIGINAL_NOT_RETAINED",
        "DIAGNOSTICS_TRUNCATED",
    }.isdisjoint(REGISTRY)
    with pytest.raises(TypeError):
        nc.DIAGNOSTIC_CODES["X_NEW"] = False


@pytest.mark.parametrize(
    "arguments",
    [
        ("date_unknown", "header", 25, "/file_header/FDT", "m"),
        ("E_FIELD", "header", 25, "/file_header/FDT", "m"),
        ("DIAGNOSTICS_TRUNCATED", "storage", None, "/diagnostics", "m"),
        ("DATE_UNKNOWN", "nowhere", 25, "/file_header/FDT", "m"),
        ("DATE_UNKNOWN", "header", False, "/file_header/FDT", "m"),
        ("DATE_UNKNOWN", "header", -1, "/file_header/FDT", "m"),
        ("DATE_UNKNOWN", "header", 25, "file_header/FDT", "m"),
        ("DATE_UNKNOWN", "header", 25, "/" + "p" * 256, "m"),
        ("DATE_UNKNOWN", "header", 25, "/file_header/FDT", "m" * 513),
    ],
)
def test_a_diagnostic_refuses_anything_outside_its_shape(arguments):
    with pytest.raises(TypeError):
        nc.Diagnostic(*arguments)


def test_a_diagnostic_renders_sorts_pickles_and_is_frozen():
    late = nc.Diagnostic("DATE_UNKNOWN", "header", 50, "/b", "m")
    early = nc.Diagnostic("TEXT_UNINTERPRETED", "header", 10, "/a", "n")
    loose = nc.Diagnostic("DATE_PARTIAL", "pixels", None, "/c", "o")
    tie = nc.Diagnostic("DATE_PARTIAL", "header", 50, "/z", "p")
    assert str(late) == "DATE_UNKNOWN @byte 50 /b: m" and str(loose) == "DATE_PARTIAL @byte - /c: o"
    assert sorted([late, early, loose, tie], key=nc.diagnostic_sort_key) == [
        loose,
        early,
        tie,
        late,
    ]
    assert nc.Diagnostic("DATE_UNKNOWN", "header", 1, "/" + "p" * 255, "m" * 512)
    for copied in (pickle.loads(pickle.dumps(late)), copy.copy(late), copy.deepcopy(late)):
        assert copied == late
    with pytest.raises(dataclasses.FrozenInstanceError):
        late.code = "DATE_PARTIAL"


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            put(kit("mono_nsif101.ntf"), 11, b"ZZZZ") + b"X",
            ("E_PROFILE", "header", 11, "/file_header/STYPE"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 9, b"04")[:-1],
            ("E_PROFILE", "header", 9, "/file_header/CLEVEL"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 360, b"A01")[:-1],
            ("E_LENGTH", "header", 342, "/file_header/FL"),
        ),
        (
            put(kit("mono_nsif101.ntf"), 25, b"20260230120000")[:-1],
            ("E_FIELD", "header", 25, "/file_header/FDT"),
        ),
        (
            put(put(kit("mono_nsif101.ntf"), 296, b"1"), 382, b"001"),
            ("E_ENCRYPTED", "header", 296, "/file_header/ENCRYP"),
        ),
        (
            container(images=[(image_sh(ABPP=b"09"), PIXELS[:3])]),
            ("E_FIELD", "segment", 772, "/segments/image[0]/ABPP"),
        ),
        (
            container(images=[(image_sh(ABPP=b"09", IXSHD=area(tre(b"bad   ", b""))), PIXELS)]),
            ("E_FIELD", "segment", 772, "/segments/image[0]/ABPP"),
        ),
        (
            container(images=[(image_sh() + b" ", PIXELS[:3])]),
            ("E_LENGTH", "segment", 843, "/segments/image[0]"),
        ),
        (
            container(
                images=[(image_sh(IXSHD=area(b"", overflow=b"009")), PIXELS)],
                texts=[(text_sh(TE=b"XX"), b"")],
            ),
            ("E_FIELD", "segment", 859, "/segments/text[0]/TE"),
        ),
        (
            container(images=[(image_sh(ABPP=b"09", IDLVL=b"000"), PIXELS)]),
            ("E_FIELD", "segment", 772, "/segments/image[0]/ABPP"),
        ),
        (
            container(images=[(image_sh(ABPP=b"09", NBPR=b"0002"), PIXELS)]),
            ("E_PROFILE", "segment", 795, "/segments/image[0]/NBPR"),
        ),
        (
            container(images=[(image_sh(NPPBH=b"0000", NBPR=b"0002", NBPC=b"0002"), PIXELS)]),
            ("E_FIELD", "segment", 803, "/segments/image[0]/NPPBH"),
        ),
        (
            container(images=[(image_sh(NBPR=b"0002", NPPBV=b"0001"), PIXELS)]),
            ("E_FIELD", "segment", 799, "/segments/image[0]/NBPC"),
        ),
        (
            put(container(images=[(image_sh(IM=b"XX"), PIXELS)]), 369, b"0000000005"),
            ("E_LENGTH", "segment", 843, "/segments/image[0]/data"),
        ),
        (
            put(put(kit("mono_nsif101.ntf"), 382, b"001"), 369, b"0000000005"),
            ("E_PROFILE", "header", 382, "/file_header/NUMX"),
        ),
    ],
    ids=[
        "stype-and-trailing",
        "clevel-and-cut",
        "numi-and-cut",
        "fdt-and-cut",
        "encryp-and-numx",
        "abpp-and-li",
        "abpp-and-cetag",
        "subheader-long-and-li",
        "dangling-and-text-marker",
        "abpp-before-idlvl",
        "grid-before-abpp",
        "zero-block-size-before-coverage",
        "row-coverage-before-column-minimality",
        "walk-before-any-subheader",
        "header-before-walk",
    ],
)
def test_the_first_fatal_error_is_the_first_failing_check_in_the_fixed_order(raw, expected):
    assert refusal(raw) == expected


# =========================================================================== REQ-015: the limits


def test_the_core1_limits():
    assert dataclasses.asdict(nc.Limits()) == {
        "input_bytes": 16_777_216,
        "twin_depth": 4,
        "twin_chars": 22_369_624,
        "segments": 256,
        "images": 64,
        "bands": 256,
        "blocks": 65_536,
        "dimension": 1_000_000,
        "tre_count": 4_096,
        "metadata_bytes": 4_194_304,
        "lut_bytes": 1_048_576,
        "output_objects": 65,
        "output_bytes": 67_108_864,
        "window_bytes": 134_217_728,
    }
    assert nc.CORE1_LIMITS == nc.Limits()
    assert 1 + nc.Limits().images == nc.Limits().output_objects
    assert 4 * -(-nc.Limits().input_bytes // 3) == nc.Limits().twin_chars
    assert nc.Limits(images=0).images == 0
    for wrong in (
        {"images": 65},
        {"images": True},
        {"images": -1},
        {"images": 1.0},
        {"tre_count": 4097},
    ):
        with pytest.raises(ValueError):
            nc.Limits(**wrong)
    with pytest.raises(dataclasses.FrozenInstanceError):
        nc.CORE1_LIMITS.images = 1
    with pytest.raises(TypeError):
        nc.parse_container(kit("mono_nsif101.ntf"))
    with pytest.raises(TypeError):
        nc.parse_container(kit("mono_nsif101.ntf"), dataclasses.asdict(nc.Limits()))
    doc = nc.Limits.__doc__
    for name in (
        "lut_bytes",
        "output_objects",
        "output_bytes",
        "window_bytes",
        "twin_depth",
        "metadata_bytes",
    ):
        # The bullet or paragraph that names the field, up to the next bullet or blank line.
        chunk = re.split(r"\n\s*\*|\n\s*\n", doc[doc.index(f"`{name}`") :])[0]
        phrase = "unreachable on the wire at the CORE-1 value; enforced and tested with an injected Limits"
        assert phrase in " ".join(chunk.split()), name


def test_the_input_cap_on_the_wire():
    at_cap = b"\xff" * 16_777_216
    assert refusal(at_cap) == ("E_MAGIC", "header", 0, "/file_header/FHDR")
    with pytest.raises(nc.NsifInputTooLarge) as caught:
        nc.parse_container(at_cap + b"\xff", LIMITS)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_LIMIT",
        "input",
        None,
        "/input",
    )
    assert "16777217" in str(caught.value) and "16777216" in str(caught.value)
    assert isinstance(caught.value, InputTooLarge)
    assert refusal({"profile": "SC4545-CORE-1"}) == ("E_FIELD", "input", None, "/input")


def test_the_image_and_segment_caps_on_the_wire():
    images = [(image_sh(), PIXELS)] * 64
    assert len(parse(container(images=images)).images) == 64
    assert refusal(container(images=images + [(image_sh(), PIXELS)])) == (
        "E_LIMIT",
        "header",
        360,
        "/file_header/NUMI",
    )
    texts = [(text_sh(), b"")] * 192
    assert len(parse(container(images=images, texts=texts)).segments) == 256
    # NUMT after 64 table entries of 16 octets, NUMS and NUMX: 360 + 3 + 1024 + 3 + 3.
    assert refusal(container(images=images, texts=texts + [(text_sh(), b"")])) == (
        "E_LIMIT",
        "header",
        1393,
        "/file_header/NUMT",
    )


def test_the_tre_cap_is_one_counter_for_the_whole_file():
    empty = tre(b"ABCDEF", b"")
    assert len(parse(container(udhd=area(empty * 4096))).extensions) == 4096
    # UDHDL 394, its content 399, the overflow number to 402, then TRE k at 402 + 11k.
    assert refusal(container(udhd=area(empty * 4097))) == (
        "E_LIMIT",
        "extension",
        45_458,
        "/file_header/UDHD/tre[4096]",
    )
    assert refusal(container(udhd=area(empty * 4096 + b"ABC"))) == (
        "E_LIMIT",
        "extension",
        45_458,
        "/file_header/UDHD/tre[4096]",
    )
    assert refusal(container(udhd=area(empty * 4095 + b"ABC"))) == (
        "E_LENGTH",
        "extension",
        45_447,
        "/file_header/UDHD/tre[4095]/CETAG",
    )
    # UDHD's 2048 TREs end at 22,930; XHDL there, its TREs from 22,938.
    assert len(parse(container(udhd=area(empty * 2048), xhd=area(empty * 2048))).extensions) == 4096
    assert refusal(container(udhd=area(empty * 2048), xhd=area(empty * 2049))) == (
        "E_LIMIT",
        "extension",
        45_466,
        "/file_header/XHD/tre[2048]",
    )
    # HL 45,463 after a full UDHD; the image's IXSHDL at 45,897, its first TRE at 45,905.
    raw = container(udhd=area(empty * 4096), images=[(image_sh(IXSHD=area(empty)), PIXELS)])
    assert refusal(raw) == ("E_LIMIT", "extension", 45_905, "/segments/image[0]/IXSHD/tre[0]")


def test_the_metadata_charge():
    found = parse(container())
    assert found.metadata_bytes == 404 + 439
    assert parse(container(), nc.Limits(metadata_bytes=843)).metadata_bytes == 843
    assert refusal(container(), nc.Limits(metadata_bytes=842)) == (
        "E_LIMIT",
        "segment",
        404,
        "/segments/image[0]/subheader",
    )
    assert refusal(container(), nc.Limits(metadata_bytes=100)) == (
        "E_LIMIT",
        "segment",
        354,
        "/file_header/HL",
    )
    # HL alone, at the cap and one over: header_only is 388 octets of header and nothing else.
    header_only = kit("header_only.ntf")
    assert parse(header_only, nc.Limits(metadata_bytes=388)).metadata_bytes == 388
    assert refusal(header_only, nc.Limits(metadata_bytes=387)) == (
        "E_LIMIT",
        "segment",
        354,
        "/file_header/HL",
    )
    # Image, graphic, text, DES and RES data is never charged.
    five = parse(l5(texts=[(text_sh(), b"T" * 99_999)], des=[(des_sh(), b"D" * 200_000)]))
    assert five.metadata_bytes == 447 + 439 + 258 + 282 + 200 + 200
    assert (
        parse(l5(texts=[(text_sh(), b"T" * 99_999)]), nc.Limits(metadata_bytes=1826)).metadata_bytes
        == 1826
    )


# =========================================================================== the twin and the screen


def twin(octets: bytes) -> dict:
    return {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(octets).decode("ascii")}


def twin_refusal(document, limits=LIMITS) -> tuple:
    with pytest.raises(nc.NsifError) as caught:
        nc.decode_twin(document, limits)
    error = caught.value
    return (error.code, error.stage, error.offset, error.path)


def test_a_twin_decodes_to_its_octets_in_either_key_order():
    mono = kit("mono_nsif101.ntf")
    assert nc.decode_twin(twin(mono), LIMITS) == mono
    reversed_order = {"wire_b64": twin(mono)["wire_b64"], "profile": "SC4545-CORE-1"}
    assert nc.decode_twin(reversed_order, LIMITS) == mono
    assert nc.decode_twin({"profile": "SC4545-CORE-1", "wire_b64": ""}, LIMITS) == b""
    assert refusal(nc.decode_twin({"profile": "SC4545-CORE-1", "wire_b64": ""}, LIMITS)) == (
        "E_LENGTH",
        "header",
        0,
        "/file_header/FHDR",
    )


@pytest.mark.parametrize(
    "document, expected",
    [
        ({"profile": "SC4545-CORE-1"}, ("E_FIELD", "input", None, "/twin")),
        ({"profile": "SC4545-CORE-1", "wire_b64": "", "x": 1}, ("E_FIELD", "input", None, "/twin")),
        ({"profile": "SC4545-CORE-1", 7: ""}, ("E_FIELD", "input", None, "/twin")),
        ({"profile": 1, "wire_b64": ""}, ("E_FIELD", "input", None, "/twin/profile")),
        (
            {"profile": "SC4545-CORE-2", "wire_b64": ""},
            ("E_PROFILE", "input", None, "/twin/profile"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": b"AAAA"},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": [[["x"]]]},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAAA AAA"},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAAA\n"},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAAAAA"},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AB=="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAB="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        # Pad bits other than the lowest: bit 3 of the last character before "==", bit 1 before
        # "=".
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AI=="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAC="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        ({"profile": "SC4545-CORE-1", "wire": ""}, ("E_FIELD", "input", None, "/twin")),
        ({"Profile": "SC4545-CORE-1", "wire_b64": ""}, ("E_FIELD", "input", None, "/twin")),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "-_8="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AA==AA=="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "AAAé"},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        (
            {"profile": "SC4545-CORE-1", "wire_b64": "===="},
            ("E_FIELD", "input", None, "/twin/wire_b64"),
        ),
        ([1], ("E_FIELD", "input", None, "/input")),
    ],
)
def test_every_twin_shape_fault(document, expected):
    assert twin_refusal(document) == expected


def test_the_twin_text_cap_on_the_wire():
    # 22,369,624 characters with two pad characters decode to exactly 16,777,216 octets.
    at_cap = "A" * 22_369_622 + "=="
    assert nc.decode_twin({"profile": "SC4545-CORE-1", "wire_b64": at_cap}, LIMITS) == bytes(
        16_777_216
    )
    del at_cap
    over = {"profile": "SC4545-CORE-1", "wire_b64": "A" * 22_369_625}
    assert twin_refusal(over) == ("E_LIMIT", "input", None, "/twin/wire_b64")
    # Unpadded at the same length the text would decode to two octets more than the binary cap.
    unpadded = {"profile": "SC4545-CORE-1", "wire_b64": "A" * 22_369_624}
    assert twin_refusal(unpadded) == ("E_LIMIT", "input", None, "/twin/wire_b64")


def test_the_twin_caps():
    assert twin_refusal(twin(bytes(9)), nc.Limits(twin_chars=8)) == (
        "E_LIMIT",
        "input",
        None,
        "/twin/wire_b64",
    )
    assert nc.decode_twin(twin(bytes(6)), nc.Limits(twin_chars=8)) == bytes(6)
    assert twin_refusal(
        {"profile": "SC4545-CORE-1", "wire_b64": "AAAAAAAA"}, nc.Limits(input_bytes=5)
    ) == (
        "E_LIMIT",
        "input",
        None,
        "/twin/wire_b64",
    )
    assert nc.decode_twin(
        {"profile": "SC4545-CORE-1", "wire_b64": "AAAAAAAA"}, nc.Limits(input_bytes=6)
    ) == bytes(6)


def test_decode_twin_admits_depth_four_shapes_and_refuses_five():
    four = {"profile": "SC4545-CORE-1", "wire_b64": [[["x"]]]}
    assert twin_refusal(four) == ("E_FIELD", "input", None, "/twin/wire_b64")
    five = {"profile": "SC4545-CORE-1", "wire_b64": [[[["x"]]]]}
    for document in (five, {**five, "extra": 1}):
        with pytest.raises(nc.NsifInputTooDeep) as caught:
            nc.decode_twin(document, LIMITS)
        assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
            "E_LIMIT",
            "input",
            None,
            "/twin",
        )
        assert isinstance(caught.value, InputTooDeep)
        with pytest.raises(nc.NsifInputTooDeep):
            nc.check_argument(document, LIMITS)
    looped: dict = {"profile": "SC4545-CORE-1"}
    looped["wire_b64"] = looped
    wide: dict = {}
    for k in range(3000):
        wide[str(k)] = wide
    for document in (looped, wide):
        with pytest.raises(nc.NsifInputTooDeep):
            nc.decode_twin(document, LIMITS)
        with pytest.raises(nc.NsifInputTooDeep):
            nc.check_argument(document, LIMITS)
    shared = [[]] * 1000
    assert twin_refusal({"profile": "SC4545-CORE-1", "wire_b64": shared}) == (
        "E_FIELD",
        "input",
        None,
        "/twin/wire_b64",
    )


def screen(raw, limits=LIMITS) -> tuple:
    with pytest.raises(nc.NsifError) as caught:
        nc.check_argument(raw, limits)
    error = caught.value
    return (type(error), error.code, error.stage, error.offset, error.path)


class Octets(bytes):
    pass


def test_the_argument_screen_takes_exactly_bytes_and_twins():
    mono = kit("mono_nsif101.ntf")
    assert nc.check_argument(mono, LIMITS) is None
    assert nc.check_argument(twin(mono), LIMITS) is None
    refused = (nc.NsifError, "E_FIELD", "input", None, "/input")
    for value in (
        bytearray(mono),
        memoryview(mono),
        mono.decode("latin-1"),
        Octets(mono),
        [mono],
        None,
        42,
        1.5,
    ):
        assert screen(value) == refused
    released = memoryview(mono)
    released.release()
    assert screen(released) == refused
    assert screen("\ud800 lone surrogate") == refused
    assert screen(b"NSIF01.0") == (nc.NsifError, "E_LENGTH", "header", 0, "/file_header/FHDR")
    assert screen(b"[" * 5 + b"]" * 5) == (
        nc.NsifError,
        "E_MAGIC",
        "header",
        0,
        "/file_header/FHDR",
    )
    assert screen(("[" * 5 + "]" * 5).encode("utf-16")) == (
        nc.NsifError,
        "E_MAGIC",
        "header",
        0,
        "/file_header/FHDR",
    )


def test_the_argument_screen_measures_every_octet_type_against_the_cap():
    big = b"\xff" * 16_777_217
    for value in (big, bytearray(big), memoryview(big), "a" * 16_777_217, "é" * 8_388_609):
        with pytest.raises(nc.NsifInputTooLarge) as caught:
            nc.check_argument(value, LIMITS)
        assert isinstance(caught.value, InputTooLarge)
        assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
            "E_LIMIT",
            "input",
            None,
            "/input",
        )
        assert "16777216" in str(caught.value)
    del big
    assert screen(b"\xff" * 16_777_216) == (
        nc.NsifError,
        "E_MAGIC",
        "header",
        0,
        "/file_header/FHDR",
    )
    assert screen(bytearray(16_777_216)) == (nc.NsifError, "E_FIELD", "input", None, "/input")
    assert screen("a" * 16_777_216) == (nc.NsifError, "E_FIELD", "input", None, "/input")
    with pytest.raises(nc.NsifInputTooLarge):
        nc.check_argument(Octets(b"\x00" * 10), nc.Limits(input_bytes=9))
    # A lone surrogate counts as the three octets its UTF-8 spelling would take, so a text of
    # surrogates meets the cap at a third of its length; dropping them would measure nothing.
    surrogates = "\ud800" * 3
    assert screen(surrogates, nc.Limits(input_bytes=9)) == (
        nc.NsifError,
        "E_FIELD",
        "input",
        None,
        "/input",
    )
    assert screen(surrogates, nc.Limits(input_bytes=8))[0] is nc.NsifInputTooLarge


class Document(dict):
    pass


def test_a_dict_subclass_is_not_a_twin():
    mono = kit("mono_nsif101.ntf")
    assert screen(Document(twin(mono))) == (nc.NsifError, "E_FIELD", "input", None, "/input")
    assert twin_refusal(Document(twin(mono))) == ("E_FIELD", "input", None, "/input")


# =========================================================================== records and imports


def test_the_container_holds_the_input_once_and_every_record_is_frozen():
    mono = kit("mono_nsif101.ntf")
    found = parse(mono)
    assert found.raw is mono and found.profile == "SC4545-CORE-1" and found.limits is LIMITS
    for record in (
        found,
        found.file_header,
        found.images[0],
        found.segments[0],
        found.file_header.security,
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, dataclasses.fields(record)[0].name, None)
    with pytest.raises(TypeError):
        found.images[0].fields["IM"] = nc.Slice(0, 0)
    assert "raw" not in repr(found)[:200]
    for name in KIT_OUTCOMES:
        if KIT_OUTCOMES[name][1] == "ok":
            found = parse(kit(name))
            for part in _every_slice(found):
                assert 0 <= part.offset <= part.offset + part.length <= found.file_size


def test_the_codec_imports_only_its_named_set_and_avoids_the_audited_words():
    source = CODEC.read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add(node.module.split(".")[0])
    allowed = {
        "__future__",
        "dataclasses",
        "fractions",
        "typing",
        "synapse_cdm",
        "binascii",
        "datetime",
        "enum",
        "re",
        "types",
        "collections",
    }
    assert roots <= allowed
    assert not re.search(r"ET\.fromstring|json\.loads|zipfile|sqlite3|gzip|zlib", source)


# =========================================================================== the fuzz seams


def test_the_three_seams_are_the_parsers_own_code_paths():
    mono = kit("unknown_duplicate_tre.ntf")
    found = parse(mono)
    layout = nc.read_layout(mono, LIMITS)
    assert layout.segments == found.segments
    assert layout.metadata_bytes == found.metadata_bytes
    assert layout.file_header == found.file_header and layout.diagnostics == found.diagnostics
    with pytest.raises(nc.NsifError):
        nc.read_layout(kit("bad_count.ntf"), LIMITS)
    unknown_date = put(mono, 25, b" " * 14)
    assert (
        nc.read_layout(unknown_date, LIMITS).diagnostics
        == parse(unknown_date).diagnostics
        == (
            nc.Diagnostic(
                "DATE_UNKNOWN",
                "header",
                25,
                "/file_header/FDT",
                "the date is all spaces or all zeros and is not interpreted",
            ),
        )
    )
    area_octets = mono[838:874]
    seam_area = nc.extension_area(area_octets, "IXSHD", LIMITS)
    assert (seam_area.section, seam_area.owner_kind, seam_area.owner_index) == ("IXSHD", "image", 0)
    assert nc.extension_area(b"00000", "UDHD", LIMITS).owner_index is None
    assert nc.extension_area(b"00000", "SXSHD", LIMITS).owner_kind == "graphic"
    assert [(t.tag, t.slice, t.data) for t in seam_area.tres] == [
        ("SCZZZZ", nc.Slice(8, 14), nc.Slice(19, 3)),
        ("SCZZZZ", nc.Slice(22, 14), nc.Slice(33, 3)),
    ]
    with_payload = nc.extension_area(
        area(b"", b"001") + CONTINUATION, "UDHD", LIMITS, overflow_at=8
    )
    assert [(t.origin, t.des_index, t.slice) for t in with_payload.tres] == [
        ("overflow", 0, nc.Slice(8, 14)),
        ("overflow", 0, nc.Slice(22, 11)),
    ]
    with pytest.raises(nc.NsifError) as caught:
        nc.extension_area(area_octets + b"X", "IXSHD", LIMITS)
    assert (caught.value.code, caught.value.offset, caught.value.path) == (
        "E_LENGTH",
        36,
        "/segments/image[0]",
    )
    with pytest.raises(nc.NsifError) as caught:
        nc.extension_area(b"00003000" + CONTINUATION, "XHD", LIMITS, overflow_at=8)
    assert (caught.value.code, caught.value.path) == ("E_OVERFLOW", "/segments/des[0]")
    subheader = mono[404:874]
    record, notes = nc.image_subheader(subheader, LIMITS, data_length=4)
    container_record = found.images[0]
    assert {n: s.offset + 404 for n, s in record.fields.items()} == {
        n: s.offset for n, s in container_record.fields.items()
    }
    assert (record.pixel_status, record.ixshd.tres[0].tag, notes) == (
        "native_supported",
        "SCZZZZ",
        (),
    )
    with pytest.raises(nc.NsifError) as caught:
        nc.image_subheader(subheader, LIMITS, data_length=3)
    assert (caught.value.code, caught.value.offset, caught.value.path) == (
        "E_LENGTH",
        470,
        "/segments/image[0]/data",
    )
    for wrong in (
        (lambda: nc.extension_area(b"00000", "DES", LIMITS)),
        (lambda: nc.image_subheader(subheader, LIMITS, -1)),
    ):
        with pytest.raises(TypeError):
            wrong()


# =========================================================================== REQ-040..044: decoding
#
# The window decoder over the kit's image vectors and the native vectors. Expected samples come
# from the kit's `expected.json`, from values written out by hand (the asymmetric literal vector,
# the interpretation table, the LUT vector) or from the vectors' stated contents below; GDAL's
# recorded reading is compared with separately. None is computed with an interleave formula.

VECTORS = FIXTURES / "vectors"
INDEPENDENT = FIXTURES / "independent"

#: Copied from the kit's `expected.json`: `samples_band_major` of its eleven image vectors.
_MONO = (0, 64, 128, 255)
_MODES = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
    21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56,
)  # fmt: skip
KIT_SAMPLES = {
    "mono_nsif101": _MONO,
    "mono_nsif100": _MONO,
    "mono_nitf210": _MONO,
    "geo_dms": _MONO,
    "unknown_duplicate_tre": _MONO,
    "mode_B": _MODES,
    "mode_P": _MODES,
    "mode_R": _MODES,
    "mode_S": _MODES,
    "uint16": (0, 256, 4095, 65535),
    "image_and_text": _MONO,
}

#: The asymmetric literal vector: NCOLS 5, NROWS 4, blocks 2 wide and 3 high on a 3 x 2 grid, two
#: bands of INT 8/8 R, pad 0xFF, LI 72. Its samples band-major, and its payload in each mode as
#: the wire order of that mode lays it out, both written out by hand.
LIT_SAMPLES = (
    10, 11, 12, 13, 14, 30, 31, 32, 33, 34,
    50, 51, 52, 53, 54, 70, 71, 72, 73, 74,
    110, 111, 112, 113, 114, 130, 131, 132, 133, 134,
    150, 151, 152, 153, 154, 170, 171, 172, 173, 174,
)  # fmt: skip
LIT_PAYLOADS = {
    "B": "0a0b1e1f32336e6f828396970c0d202134357071848598990eff22ff36ff72ff86ff9aff4647ffffffffaaab"
    "ffffffff4849ffffffffacadffffffff4affffffffffaeffffffffff",
    "P": "0a6e0b6f1e821f83329633970c700d7120842185349835990e72ffff2286ffff369affff46aa47abffffffff"
    "ffffffff48ac49adffffffffffffffff4aaeffffffffffffffffffff",
    "R": "0a0b6e6f1e1f8283323396970c0d707120218485343598990eff72ff22ff86ff36ff9aff4647aaabffffffff"
    "ffffffff4849acadffffffffffffffff4affaeffffffffffffffffff",
    "S": "0a0b1e1f32330c0d202134350eff22ff36ff4647ffffffff4849ffffffff4affffffffff6e6f828396977071"
    "8485989972ff86ff9affaaabffffffffacadffffffffaeffffffffff",
}

#: Each native vector as the subheader states it: IMODE, PVTYPE, NBPP, ABPP, PJUST, bands,
#: (NCOLS, NROWS), (NBPR, NBPC), (NPPBH, NPPBV), the data segment's offset and LI. The offset is
#: the kit layout's: HL 404, a 439-octet one-band subheader, 13 octets per further band, 5 for
#: XBANDS, 60 for IGEOLO, 17 for three four-entry LUTs.
VECTOR_SHAPES = {
    **{
        f"native_lit_{m.lower()}": (m, "INT", 8, 8, "R", 2, (5, 4), (3, 2), (2, 3), 856, 72)
        for m in "BPRS"
    },
    **{
        f"native_edge8_{m.lower()}": (m, "INT", 8, 8, "R", 3, (7, 5), (2, 2), (4, 4), 869, 192)
        for m in "BPRS"
    },
    **{
        f"native_edge16_{m.lower()}": (m, "INT", 16, 16, "R", 3, (7, 5), (3, 3), (3, 2), 869, 324)
        for m in "BPRS"
    },
    "native_nppb_zero": ("B", "INT", 8, 8, "R", 1, (5, 3), (1, 1), (0, 0), 843, 15),
    "native_nppbh_zero_only": ("B", "INT", 8, 8, "R", 1, (5, 3), (1, 2), (0, 2), 843, 20),
    "native_one_block_padded": ("B", "INT", 8, 8, "R", 1, (5, 3), (1, 1), (8, 4), 843, 32),
    "native_pjust_r_12in16_dirty": ("B", "INT", 16, 12, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_pjust_l_12in16": ("B", "INT", 16, 12, "L", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_pjust_l_12in16_dirty": ("B", "INT", 16, 12, "L", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_pjust_l_5in8": ("B", "INT", 8, 5, "L", 1, (3, 2), (1, 1), (3, 2), 843, 6),
    "native_si8": ("B", "SI", 8, 8, "R", 1, (3, 2), (1, 1), (3, 2), 843, 6),
    "native_si16": ("B", "SI", 16, 16, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si12_r_zerofill": ("B", "SI", 16, 12, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si12_r_signext": ("B", "SI", 16, 12, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si12_r_mixed": ("B", "SI", 16, 12, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si12_l": ("B", "SI", 16, 12, "L", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si12_l_dirty": ("B", "SI", 16, 12, "L", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_si1in8_r": ("B", "SI", 8, 1, "R", 1, (3, 2), (1, 1), (3, 2), 843, 6),
    "native_int8in16_r": ("B", "INT", 16, 8, "R", 1, (3, 2), (1, 1), (3, 2), 843, 12),
    "native_int5in8_r_dirty": ("B", "INT", 8, 5, "R", 1, (3, 2), (1, 1), (3, 2), 843, 6),
    "native_si5in8_l_dirty": ("B", "SI", 8, 5, "L", 1, (3, 2), (1, 1), (3, 2), 843, 6),
    **{
        f"native_nbands9_{m.lower()}": (m, "INT", 8, 8, "R", 9, (5, 3), (2, 2), (3, 2), 947, 216)
        for m in "BPRS"
    },
    **{
        f"native_xbands10_{m.lower()}": (m, "INT", 8, 8, "R", 10, (5, 3), (2, 2), (3, 2), 965, 240)
        for m in "BPRS"
    },
    **{
        f"native_xbands256_{m.lower()}": (
            m,
            "INT",
            8,
            8,
            "R",
            256,
            (5, 3),
            (2, 2),
            (3, 2),
            4163,
            6144,
        )
        for m in "BPRS"
    },
    "native_lut3": ("B", "INT", 8, 8, "R", 1, (2, 2), (1, 1), (2, 2), 860, 4),
    **{
        f"native_geo_{kind}": ("B", "INT", 8, 8, "R", 1, (5, 3), (1, 1), (5, 3), 903, 15)
        for kind in ("g_northup", "g_southup", "d_northup", "d_southup")
    },
}

#: The fifteen interpretation vectors (one band, 2 rows x 3 columns): NBPP/ABPP/PJUST/PVTYPE,
#: the storage octets, the interpreted values and the element type, all written out by hand.
INTERPRETATION = {
    "native_pjust_r_12in16_dirty": (
        "16/12/R/INT", "0000 0001 07FF 0800 0FFE FFFF", (0, 1, 2047, 2048, 4094, 4095), "uint16"
    ),
    "native_pjust_l_12in16": (
        "16/12/L/INT", "0000 0010 7FF0 8000 FFE0 FFF0", (0, 1, 2047, 2048, 4094, 4095), "uint16"
    ),
    "native_pjust_l_12in16_dirty": (
        "16/12/L/INT", "0000 0010 7FF5 8000 FFE0 FFF0", (0, 1, 2047, 2048, 4094, 4095), "uint16"
    ),
    "native_pjust_l_5in8": ("8/5/L/INT", "00 08 78 80 F0 F8", (0, 1, 15, 16, 30, 31), "uint8"),
    "native_si8": ("8/8/R/SI", "80 FF 00 7F 01 FE", (-128, -1, 0, 127, 1, -2), "int8"),
    "native_si16": (
        "16/16/R/SI", "8000 FFFF 0000 7FFF FFFE 0001", (-32768, -1, 0, 32767, -2, 1), "int16"
    ),
    "native_si12_r_zerofill": (
        "16/12/R/SI", "0800 0FFF 0000 07FF 0001 0FFE", (-2048, -1, 0, 2047, 1, -2), "int16"
    ),
    "native_si12_r_signext": (
        "16/12/R/SI", "F800 FFFF 0000 07FF 0001 FFFE", (-2048, -1, 0, 2047, 1, -2), "int16"
    ),
    "native_si12_r_mixed": (
        "16/12/R/SI", "F800 0FFF 1000 17FF F7FF 8800", (-2048, -1, 0, 2047, 2047, -2048), "int16"
    ),
    "native_si12_l": (
        "16/12/L/SI", "8000 FFF0 0000 7FF0 0010 FFE0", (-2048, -1, 0, 2047, 1, -2), "int16"
    ),
    "native_si12_l_dirty": (
        "16/12/L/SI", "800F FFF0 0000 7FF0 0010 FFE1", (-2048, -1, 0, 2047, 1, -2), "int16"
    ),
    "native_si1in8_r": ("8/1/R/SI", "00 01 FF FE 80 7F", (0, -1, -1, 0, 0, -1), "int8"),
    "native_int8in16_r": (
        "16/8/R/INT", "0000 00FF 0100 01FF FF00 0080", (0, 255, 0, 255, 0, 128), "uint16"
    ),
    "native_int5in8_r_dirty": ("8/5/R/INT", "00 01 1F 20 E0 FF", (0, 1, 31, 0, 0, 31), "uint8"),
    "native_si5in8_l_dirty": ("8/5/L/SI", "80 F8 00 78 08 F1", (-16, -1, 0, 15, 1, -2), "int8"),
}  # fmt: skip

#: Discarded-bit counts of a full interpreted window, (nonzero, sign-extended), by hand from the
#: storage octets above.
FILL_COUNTS = {
    "native_pjust_r_12in16_dirty": (1, 0),
    "native_pjust_l_12in16": (0, 0),
    "native_pjust_l_12in16_dirty": (1, 0),
    "native_pjust_l_5in8": (0, 0),
    "native_si8": (0, 0),
    "native_si16": (0, 0),
    "native_si12_r_zerofill": (0, 0),
    "native_si12_r_signext": (0, 3),
    "native_si12_r_mixed": (4, 1),
    "native_si12_l": (0, 0),
    "native_si12_l_dirty": (2, 0),
    "native_si1in8_r": (3, 1),
    "native_int8in16_r": (3, 0),
    "native_int5in8_r_dirty": (3, 0),
    "native_si5in8_l_dirty": (1, 0),
}

FILL_NONZERO = "some samples in this window have nonzero bits outside ABPP"
FILL_SIGN_EXTENDED = "some samples in this window carry sign-extension bits outside ABPP"


def content8(band: int, row: int, column: int) -> int:
    """The stated content of the 8-bit native vectors: never 255, the pad value."""
    return (37 * band + 11 * row + 3 * column + 1) % 251


def content16(band: int, row: int, column: int) -> int:
    """The stated content of the 16-bit native vectors: never 65535, the pad value."""
    return (1009 * band + 257 * row + 31 * column + 1) % 65521


def stated(content, x: int, y: int, width: int, height: int, bands: tuple[int, ...]) -> tuple:
    """A window of a stated content, band-major in request order (REQ-041's [band,row,column])."""
    return tuple(
        content(b, row, column)
        for b in bands
        for row in range(y, y + height)
        for column in range(x, x + width)
    )


def vector(stem: str) -> bytes:
    return (VECTORS / f"{stem}.ntf").read_bytes()


def image_bearing(stem: str) -> bytes:
    return kit(f"{stem}.ntf") if stem in KIT_SAMPLES else vector(stem)


def full(found: nc.Container, storage: bool = False) -> nc.SampleWindow:
    image = found.images[0]
    bands = tuple(range(image.band_count))
    return nc.decode_nc_window(found, 0, 0, 0, image.ncols, image.nrows, bands, storage=storage)


def window_refusal(found, *arguments, **keywords) -> tuple:
    with pytest.raises(nc.NsifError) as caught:
        nc.decode_nc_window(found, *arguments, **keywords)
    error = caught.value
    return (error.code, error.stage, error.offset, error.path, error.explanation)


def data_octets(found: nc.Container, image_index: int = 0) -> bytes:
    data = found.images[image_index].segment.data
    return found.raw[data.offset : data.offset + data.length]


def test_the_native_vectors_have_the_shapes_their_names_state():
    assert sorted(VECTOR_SHAPES) == sorted(NATIVE_STEMS)
    assert sorted(p.stem for p in VECTORS.glob("*.ntf")) == sorted(NATIVE_STEMS)
    for stem, shape in VECTOR_SHAPES.items():
        found = parse(vector(stem))
        assert len(found.images) == 1 and found.diagnostics == (), stem
        image = found.images[0]
        assert (
            image.imode,
            image.pvtype,
            image.nbpp,
            image.abpp,
            image.pjust,
            image.band_count,
            (image.ncols, image.nrows),
            (image.nbpr, image.nbpc),
            (image.nppbh, image.nppbv),
            image.segment.data.offset,
            image.segment.data.length,
        ) == shape, stem
        assert (image.ic, image.pixel_status, image.pixel_reason) == (
            "NC",
            "native_supported",
            None,
        )
        # The kit's header layout, so the source identity fields are set.
        assert found.raw[15:25] == b"SCFIX     " and found.file_header.fdt.status == "valid"
        assert found.raw[406:416] == b"SCFIX0001 "


def test_the_literal_vector_is_written_in_each_modes_wire_order():
    builder = _build_fixtures_module()
    planes = [
        [list(LIT_SAMPLES[20 * b + 5 * row : 20 * b + 5 * row + 5]) for row in range(4)]
        for b in range(2)
    ]
    for mode, payload in LIT_PAYLOADS.items():
        assert builder.physical_payload(planes, 2, 3, mode, 8, 0xFF).hex() == payload
        assert data_octets(parse(vector(f"native_lit_{mode.lower()}"))).hex() == payload
    assert len(set(LIT_PAYLOADS.values())) == 4


@pytest.mark.parametrize("stem", sorted(KIT_SAMPLES))
def test_every_kit_image_vector_decodes_to_the_kits_band_major_samples(stem):
    found = parse(kit(f"{stem}.ntf"))
    for storage in (False, True):
        window = full(found, storage)
        assert window.values() == KIT_SAMPLES[stem]
        assert window.dtype == ("uint16" if stem == "uint16" else "uint8")
        assert window.kind == ("storage" if storage else "interpreted")
        assert (window.fill_bits_nonzero, window.fill_bits_sign_extended) == (0, 0)
        assert window.diagnostics == ()
    image = found.images[0]
    assert window.shape == (image.band_count, image.nrows, image.ncols)


@pytest.mark.parametrize("mode", "BPRS")
def test_the_literal_vector_decodes_in_every_mode(mode):
    found = parse(vector(f"native_lit_{mode.lower()}"))
    assert full(found).values() == LIT_SAMPLES
    # Band reorder across a partial edge block in both directions.
    window = nc.decode_nc_window(found, 0, 1, 2, 3, 2, (1, 0))
    assert window.values() == (151, 152, 153, 171, 172, 173, 51, 52, 53, 71, 72, 73)
    assert window.shape == (2, 2, 3) and window.bands == (1, 0)
    assert nc.decode_nc_window(found, 0, 1, 1, 3, 3, (0,)).values() == (
        31, 32, 33, 51, 52, 53, 71, 72, 73,
    )  # fmt: skip
    # The last visible pixel, in the partial block at the grid's corner.
    assert nc.decode_nc_window(found, 0, 4, 3, 1, 1, (1, 0)).values() == (174, 74)


#: A sub-window of each shape that crosses a block boundary in both directions.
_CROSSING = {"edge8": (2, 2, 4, 3), "edge16": (2, 1, 4, 3), "bands": (2, 1, 3, 2)}


@pytest.mark.parametrize("mode", "BPRS")
@pytest.mark.parametrize("prefix", ["edge8", "edge16", "nbands9", "xbands10", "xbands256"])
def test_the_edge_and_band_vectors_decode_to_their_stated_content(prefix, mode):
    found = parse(vector(f"native_{prefix}_{mode.lower()}"))
    image = found.images[0]
    content = content16 if prefix == "edge16" else content8
    every = tuple(range(image.band_count))
    assert full(found).values() == stated(content, 0, 0, image.ncols, image.nrows, every)
    x, y, width, height = _CROSSING.get(prefix, _CROSSING["bands"])
    bands = (image.band_count - 1, 0)
    window = nc.decode_nc_window(found, 0, x, y, width, height, bands)
    assert window.values() == stated(content, x, y, width, height, bands)
    assert window.dtype == ("uint16" if prefix == "edge16" else "uint8")


@pytest.mark.parametrize(
    "stem", ["native_nppb_zero", "native_nppbh_zero_only", "native_one_block_padded"]
)
def test_zero_and_oversized_block_sizes_decode_to_the_stated_content(stem):
    found = parse(vector(stem))
    assert full(found).values() == full(found, storage=True).values()
    assert full(found).values() == stated(content8, 0, 0, 5, 3, (0,))
    assert nc.decode_nc_window(found, 0, 1, 1, 4, 2, (0,)).values() == stated(
        content8, 1, 1, 4, 2, (0,)
    )


#: Every vector with partial edge blocks, and the octet width of its pad sentinel.
PADDED = {
    **{f"native_{prefix}_{m}": 1 for prefix in ("lit", "edge8") for m in "bprs"},
    **{f"native_edge16_{m}": 2 for m in "bprs"},
    **{
        f"native_{prefix}_{m}": 1 for prefix in ("nbands9", "xbands10", "xbands256") for m in "bprs"
    },
    "native_nppbh_zero_only": 1,
    "native_one_block_padded": 1,
}


@pytest.mark.parametrize("stem", sorted(PADDED))
def test_edge_fill_is_counted_in_li_and_never_exposed(stem):
    found = parse(vector(stem))
    octets = PADDED[stem]
    sentinel = (1 << (8 * octets)) - 1
    payload = data_octets(found)
    elements = [
        int.from_bytes(payload[k : k + octets], "big") for k in range(0, len(payload), octets)
    ]
    image = found.images[0]
    visible = image.ncols * image.nrows * image.band_count
    assert elements.count(sentinel) == len(elements) - visible > 0
    for storage in (False, True):
        assert sentinel not in full(found, storage).values()
    # A pad column or row is never addressable.
    assert window_refusal(found, 0, image.ncols, 0, 1, 1, (0,))[3] == "/window/width"
    assert window_refusal(found, 0, 0, image.nrows, 1, 1, (0,))[3] == "/window/height"


@pytest.mark.parametrize("stem", sorted(INTERPRETATION))
def test_every_interpretation_vector_gives_its_literal_values(stem):
    cell, storage_hex, values, dtype = INTERPRETATION[stem]
    nbpp, abpp, pjust, pvtype = cell.split("/")
    found = parse(vector(stem))
    image = found.images[0]
    assert (image.nbpp, image.abpp, image.pjust, image.pvtype) == (
        int(nbpp),
        int(abpp),
        pjust,
        pvtype,
    )
    storage = bytes.fromhex(storage_hex)
    assert data_octets(found) == storage
    interpreted = full(found)
    assert interpreted.values() == values and interpreted.dtype == dtype
    raw = full(found, storage=True)
    assert raw.data == storage and raw.dtype == ("uint16" if nbpp == "16" else "uint8")
    width = int(nbpp) // 8
    assert raw.values() == tuple(
        int.from_bytes(storage[k : k + width], "big") for k in range(0, len(storage), width)
    )


def test_the_interpretation_vectors_cover_every_type_justification_and_width():
    cells = {
        tuple(INTERPRETATION[stem][0].split("/")[i] for i in (3, 2, 0)) for stem in INTERPRETATION
    }
    assert cells == {(t, j, w) for t in ("INT", "SI") for j in ("L", "R") for w in ("8", "16")}


@pytest.mark.parametrize("stem", sorted(FILL_COUNTS))
def test_discarded_bits_are_counted_over_the_returned_samples_only(stem):
    found = parse(vector(stem))
    assert found.diagnostics == ()
    window = full(found)
    nonzero, sign_extended = FILL_COUNTS[stem]
    assert (window.fill_bits_nonzero, window.fill_bits_sign_extended) == FILL_COUNTS[stem]
    codes = ["FILL_BITS_NONZERO"] * bool(nonzero) + ["FILL_BITS_SIGN_EXTENDED"] * bool(
        sign_extended
    )
    assert [d.code for d in window.diagnostics] == codes
    stored = full(found, storage=True)
    assert (stored.fill_bits_nonzero, stored.fill_bits_sign_extended, stored.diagnostics) == (
        0,
        0,
        (),
    )


def test_the_fill_bit_diagnostics_name_the_first_source_octet_of_their_class():
    data = "/segments/image[0]/data"
    mixed = parse(vector("native_si12_r_mixed"))
    assert full(mixed).diagnostics == (
        nc.Diagnostic("FILL_BITS_NONZERO", "pixels", 847, data, FILL_NONZERO),
        nc.Diagnostic("FILL_BITS_SIGN_EXTENDED", "pixels", 843, data, FILL_SIGN_EXTENDED),
    )
    signext = parse(vector("native_si12_r_signext"))
    # Its second row, `07FF 0001 FFFE`: only the last sample is sign-extended.
    row = nc.decode_nc_window(signext, 0, 0, 1, 3, 1, (0,))
    assert row.diagnostics == (
        nc.Diagnostic("FILL_BITS_SIGN_EXTENDED", "pixels", 853, data, FILL_SIGN_EXTENDED),
    )
    assert (row.fill_bits_nonzero, row.fill_bits_sign_extended) == (0, 1)
    # `07FF 0001`: non-negative samples only, so nothing is discarded.
    quiet = nc.decode_nc_window(signext, 0, 0, 1, 2, 1, (0,))
    assert (quiet.fill_bits_nonzero, quiet.fill_bits_sign_extended, quiet.diagnostics) == (0, 0, ())
    assert full(parse(vector("native_int5in8_r_dirty"))).diagnostics == (
        nc.Diagnostic("FILL_BITS_NONZERO", "pixels", 846, data, FILL_NONZERO),
    )
    assert full(parse(vector("native_si5in8_l_dirty"))).diagnostics == (
        nc.Diagnostic("FILL_BITS_NONZERO", "pixels", 848, data, FILL_NONZERO),
    )
    assert nc.DIAGNOSTIC_CODES["FILL_BITS_NONZERO"] is False
    assert nc.DIAGNOSTIC_CODES["FILL_BITS_SIGN_EXTENDED"] is False


def test_the_fill_bit_offset_is_the_lowest_source_octet_not_the_first_returned():
    # Two bands interleaved by pixel (P), 12 significant bits right-justified in 16, each band
    # `F800 1000`: F800 is a sign-extended -2048, 1000 a stray bit above a zero. On the wire band
    # 0 pixel 0 is at 856 (HL 404, a two-band subheader of 452), band 1 pixel 0 at 858, band 0
    # pixel 1 at 860, band 1 pixel 1 at 862. Asked for bands (1, 0), the window returns band 1's
    # samples first, but each diagnostic names its class's lowest source offset.
    builder = _build_fixtures_module()
    samples = [[[0xF800, 0x1000]], [[0xF800, 0x1000]]]
    segment = builder.native_image(samples, 2, 1, "P", nbpp=16, abpp=12, pvtype="SI")
    found = parse(builder.container([segment]))
    assert data_octets(found).hex() == "f800f80010001000"
    window = nc.decode_nc_window(found, 0, 0, 0, 2, 1, (1, 0))
    assert window.values() == (-2048, 0, -2048, 0)
    assert (window.fill_bits_nonzero, window.fill_bits_sign_extended) == (2, 2)
    data = "/segments/image[0]/data"
    assert window.diagnostics == (
        nc.Diagnostic("FILL_BITS_NONZERO", "pixels", 860, data, FILL_NONZERO),
        nc.Diagnostic("FILL_BITS_SIGN_EXTENDED", "pixels", 856, data, FILL_SIGN_EXTENDED),
    )


def test_the_left_justified_fill_bit_offset_is_the_lowest_source_octet_too():
    # Two bands interleaved by pixel (P), 12 significant bits left-justified in 16 (the low four
    # are fill): band 0 is `1235 4560`, band 1 `7890 ABC7`, so band 0 pixel 0 (at 856) and band 1
    # pixel 1 (at 862) carry nonzero fill. On the wire: 856 b0p0, 858 b1p0, 860 b0p1, 862 b1p1.
    # Asked for bands (1, 0), the window meets the dirty sample at 862 first; the diagnostic still
    # names the lowest source octet, 856.
    builder = _build_fixtures_module()
    samples = [[[0x1235, 0x4560]], [[0x7890, 0xABC7]]]
    segment = builder.native_image(samples, 2, 1, "P", nbpp=16, abpp=12, pjust="L")
    found = parse(builder.container([segment]))
    assert data_octets(found).hex() == "123578904560abc7"
    window = nc.decode_nc_window(found, 0, 0, 0, 2, 1, (1, 0))
    assert window.values() == (0x789, 0xABC, 0x123, 0x456)
    assert (window.fill_bits_nonzero, window.fill_bits_sign_extended) == (2, 0)
    assert window.diagnostics == (
        nc.Diagnostic("FILL_BITS_NONZERO", "pixels", 856, "/segments/image[0]/data", FILL_NONZERO),
    )


def test_the_decoder_signature_and_its_two_views():
    parameters = list(inspect.signature(nc.decode_nc_window).parameters.values())
    assert [p.name for p in parameters] == [
        "container",
        "image_index",
        "x",
        "y",
        "width",
        "height",
        "bands",
        "storage",
    ]
    assert all(p.kind is p.POSITIONAL_OR_KEYWORD for p in parameters[:7])
    assert parameters[7].kind is parameters[7].KEYWORD_ONLY and parameters[7].default is False
    found = parse(vector("native_pjust_l_12in16"))
    assert full(found, storage=True).values() == (0, 16, 32752, 32768, 65504, 65520)
    assert full(found).values() == (0, 1, 2047, 2048, 4094, 4095)
    # Pure: the same request gives the same window.
    assert full(found) == full(found) and full(found).data == full(found).data


def test_the_sample_window_is_band_major_big_endian_bytes():
    assert [f.name for f in dataclasses.fields(nc.SampleWindow)] == [
        "image_index",
        "x",
        "y",
        "width",
        "height",
        "bands",
        "kind",
        "dtype",
        "data",
        "fill_bits_nonzero",
        "fill_bits_sign_extended",
        "diagnostics",
    ]
    window = full(parse(kit("uint16.ntf")))
    assert (window.dtype, window.data.hex(), window.values()) == (
        "uint16",
        "000001000fffffff",
        (0, 256, 4095, 65535),
    )
    assert (window.shape, window.itemsize, type(window.data)) == ((1, 2, 2), 2, bytes)
    zerofill = full(parse(vector("native_si12_r_zerofill")))
    assert (zerofill.dtype, zerofill.data.hex()) == ("int16", "f800ffff000007ff0001fffe")
    si8 = parse(vector("native_si8"))
    assert (full(si8).dtype, full(si8).data.hex(), full(si8).itemsize) == (
        "int8",
        "80ff007f01fe",
        1,
    )
    assert (full(si8, storage=True).dtype, full(si8, storage=True).values()) == (
        "uint8",
        (128, 255, 0, 127, 1, 254),
    )
    assert full(parse(vector("native_int8in16_r"))).dtype == "uint16"
    assert all(type(v) is int for v in window.values())
    with pytest.raises(dataclasses.FrozenInstanceError):
        window.data = b""


# The request checks, in order, on the literal vector (5 x 4, two bands).
WINDOW = "/window"


@pytest.mark.parametrize(
    "arguments, keywords, expected",
    [
        ((True, 0, 0, 1, 1, (0,)), {}, ("/window/image_index", "image_index is not an int")),
        ((1, 0, 0, 1, 1, (0,)), {}, ("/window/image_index", "no such image")),
        ((-1, 0, 0, 1, 1, (0,)), {}, ("/window/image_index", "no such image")),
        ((0, 0, 0, 1, 1, (0,)), {"storage": 1}, ("/window/storage", "storage is not a bool")),
        ((0, 1.0, 0, 1, 1, (0,)), {}, ("/window/x", "x is not an int")),
        ((0, 0, True, 1, 1, (0,)), {}, ("/window/y", "y is not an int")),
        ((0, 0, 0, 1.0, 1, (0,)), {}, ("/window/width", "width is not an int")),
        ((0, 0, 0, 1, None, (0,)), {}, ("/window/height", "height is not an int")),
        ((0, -1, 0, 1, 1, (0,)), {}, ("/window/x", "x is negative")),
        ((0, 0, -1, 1, 1, (0,)), {}, ("/window/y", "y is negative")),
        ((0, 0, 0, 0, 1, (0,)), {}, ("/window/width", "width is not positive")),
        ((0, 0, 0, 1, 0, (0,)), {}, ("/window/height", "height is not positive")),
        ((0, 4, 0, 2, 1, (0,)), {}, ("/window/width", "the window extends past NCOLS")),
        ((0, 0, 2, 1, 3, (0,)), {}, ("/window/height", "the window extends past NROWS")),
        ((0, 0, 0, 1, 1, [0]), {}, ("/window/bands", "bands must be a tuple")),
        ((0, 0, 0, 1, 1, ()), {}, ("/window/bands", "no band requested")),
        (
            (0, 0, 0, 1, 1, (0, 1, 0)),
            {},
            ("/window/bands", "more band indexes than the image has bands"),
        ),
        ((0, 0, 0, 1, 1, (1, 1)), {}, ("/window/bands", "duplicate band index")),
        ((0, 0, 0, 1, 1, (2,)), {}, ("/window/bands", "no such band")),
        ((0, 0, 0, 1, 1, (-1,)), {}, ("/window/bands", "no such band")),
        ((0, 0, 0, 1, 1, (True,)), {}, ("/window/bands", "band index is not an int")),
        ((0, 0, 0, 1, 1, (0, 1.0)), {}, ("/window/bands", "band index is not an int")),
        # The first failing check wins, whatever comes later.
        (
            (True, -1, 0, 1, 1, ()),
            {"storage": 1},
            ("/window/image_index", "image_index is not an int"),
        ),
        ((0, 1.0, 0, 1, 1, (0,)), {"storage": 1}, ("/window/storage", "storage is not a bool")),
        ((0, -1, 1.0, 1, 1, (0,)), {}, ("/window/y", "y is not an int")),
        ((0, 4, 0, 2, 1, (5,)), {}, ("/window/width", "the window extends past NCOLS")),
        (
            (0, 0, 0, 1, 1, (0, 0, 1)),
            {},
            ("/window/bands", "more band indexes than the image has bands"),
        ),
    ],
)
def test_every_window_request_fault_is_refused_in_order(arguments, keywords, expected):
    found = parse(vector("native_lit_b"))
    assert window_refusal(found, *arguments, **keywords) == ("E_FIELD", "pixels", None, *expected)


def test_the_container_is_checked_first_and_an_empty_one_has_no_image():
    for wrong in (kit("mono_nsif101.ntf"), None, {"images": ()}):
        assert window_refusal(wrong, True, -1, 0, 0, 0, []) == (
            "E_FIELD",
            "pixels",
            None,
            "/window/container",
            "the container is not a parsed Container",
        )
    assert window_refusal(parse(kit("header_only.ntf")), 0, 0, 0, 1, 1, (0,)) == (
        "E_FIELD",
        "pixels",
        None,
        "/window/image_index",
        "no such image",
    )


_NO_PATH = "no pixel path is enabled for this compression code in this deployment"
_UNNAMED = "compression code is not one this profile names"
_NO_TYPE = "no native sample path for this sample type"
_NO_LAYOUT = "IMODE S needs at least two bands and two blocks in this profile"


@pytest.mark.parametrize(
    "over, reason, code, refusal_code, offset, field, message",
    [
        (
            {"IC": b"C8", "COMRAT": b"1.0 "},
            "compression_not_enabled",
            "COMPRESSION_NOT_ENABLED",
            "E_CODEC",
            777,
            "IC",
            _NO_PATH,
        ),
        (
            {"IC": b"NM"},
            "compression_not_enabled",
            "COMPRESSION_NOT_ENABLED",
            "E_CODEC",
            777,
            "IC",
            _NO_PATH,
        ),
        (
            {"IC": b"ZZ", "COMRAT": b"1.0 "},
            "unsupported_compression",
            "UNSUPPORTED_COMPRESSION",
            "E_CODEC",
            777,
            "IC",
            _UNNAMED,
        ),
        (
            {"PVTYPE": b"R  ", "ABPP": b"32", "NBPP": b"32"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            753,
            "PVTYPE",
            _NO_TYPE,
        ),
        (
            {"PVTYPE": b"C  ", "ABPP": b"32", "NBPP": b"64"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            753,
            "PVTYPE",
            _NO_TYPE,
        ),
        (
            {"PVTYPE": b"B  ", "ABPP": b"01", "NBPP": b"01"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            753,
            "PVTYPE",
            _NO_TYPE,
        ),
        (
            {"PVTYPE": b"int"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            753,
            "PVTYPE",
            _NO_TYPE,
        ),
        (
            {"ABPP": b"12", "NBPP": b"12"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            811,
            "NBPP",
            _NO_TYPE,
        ),
        (
            {"ABPP": b"32", "NBPP": b"32"},
            "unsupported_sample_type",
            "UNSUPPORTED_SAMPLE_TYPE",
            "E_PROFILE",
            811,
            "NBPP",
            _NO_TYPE,
        ),
        (
            {"IMODE": b"S", "NBPR": b"0002", "NPPBH": b"0001"},
            "unsupported_sample_layout",
            "UNSUPPORTED_SAMPLE_LAYOUT",
            "E_PROFILE",
            794,
            "IMODE",
            _NO_LAYOUT,
        ),
        (
            {"IMODE": b"S", "NBANDS": b"2", "BANDS": BAND * 2},
            "unsupported_sample_layout",
            "UNSUPPORTED_SAMPLE_LAYOUT",
            "E_PROFILE",
            807,
            "IMODE",
            _NO_LAYOUT,
        ),
    ],
    ids=[
        "C8",
        "NM",
        "ZZ",
        "R-32",
        "C-64",
        "B-01",
        "int",
        "NBPP-12",
        "NBPP-32",
        "S-one-band",
        "S-one-block",
    ],
)
def test_every_cell_outside_the_native_profile_is_kept_and_refused(
    over, reason, code, refusal_code, offset, field, message
):
    data = b"\x5a\x01\x02"
    found = parse(container(images=[(image_sh(**over), data)]))
    image = found.images[0]
    assert (image.pixel_status, image.pixel_reason) == ("unsupported", reason)
    path = f"/segments/image[0]/{field}"
    assert found.diagnostics == (nc.Diagnostic(code, "pixels", offset, path, message),)
    assert nc.DIAGNOSTIC_CODES[code] is False
    # The samples are preserved as they are and never decoded, whatever the request.
    assert data_octets(found) == data
    for request in ((0, 0, 0, 1, 1, (0,)), (0, 99, 0, 1, 1, (0,)), (0, -1, -1, 0, 0, ())):
        assert window_refusal(found, *request) == (refusal_code, "pixels", offset, path, message)


def test_the_native_window_cap_is_checked_before_the_output_exists():
    found = parse(vector("native_lit_b"), nc.Limits(window_bytes=12))
    assert nc.decode_nc_window(found, 0, 0, 0, 3, 2, (0, 1)).values() == (
        10, 11, 12, 30, 31, 32, 110, 111, 112, 130, 131, 132,
    )  # fmt: skip
    found = parse(vector("native_lit_b"), nc.Limits(window_bytes=11))
    assert window_refusal(found, 0, 0, 0, 3, 2, (0, 1)) == (
        "E_LIMIT",
        "pixels",
        None,
        "/window",
        "the window is larger than the native window cap",
    )
    # Bands are refused before the cap: a duplicate is an input error, not a size.
    assert window_refusal(found, 0, 0, 0, 3, 2, (1, 1))[3:] == (
        "/window/bands",
        "duplicate band index",
    )
    # A request cannot exceed its image's payload (no band twice), so the default cap is never
    # reached from the wire: the input cap is below it.
    assert nc.Limits().input_bytes < nc.Limits().window_bytes == 134_217_728
    assert found.limits.window_bytes == 11


def _large_uint16_image() -> bytes:
    """One 2000 x 2000 uint16 image in a single block: 8,000,000 data octets."""
    image = image_sh(
        NROWS=b"00002000",
        NCOLS=b"00002000",
        ABPP=b"16",
        NBPP=b"16",
        NPPBH=b"2000",
        NPPBV=b"2000",
    )
    return container(images=[(image, bytes(8_000_000))])


def test_a_window_reads_in_place_and_a_refused_one_allocates_nothing_proportional():
    raw = _large_uint16_image()
    found = parse(raw, nc.Limits(window_bytes=7_999_999))
    tracemalloc.start()
    try:
        with pytest.raises(nc.NsifError) as caught:
            nc.decode_nc_window(found, 0, 0, 0, 2000, 2000, (0,))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (caught.value.code, caught.value.path) == ("E_LIMIT", "/window")
    assert peak < 65_536
    found = parse(raw)
    tracemalloc.start()
    try:
        window = nc.decode_nc_window(found, 0, 1000, 1000, 64, 64, (0,))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(window.data) == 8192 and set(window.data) == {0}
    assert peak <= 2 * 8192 + 65_536


def test_the_data_length_is_rechecked_before_any_read():
    found = parse(vector("native_edge8_b"))
    image = found.images[0]
    short = dataclasses.replace(image.segment, data=nc.Slice(869, 191))
    forged = dataclasses.replace(found, images=(dataclasses.replace(image, segment=short),))
    assert window_refusal(forged, 0, 0, 0, 1, 1, (0,)) == (
        "E_LENGTH",
        "pixels",
        869,
        "/segments/image[0]/data",
        "the data length differs from the native sample length",
    )
    cut = dataclasses.replace(found, raw=found.raw[:-1])
    assert window_refusal(cut, 0, 0, 0, 1, 1, (0,))[:4] == (
        "E_LENGTH",
        "pixels",
        869,
        "/segments/image[0]/data",
    )


def test_li_is_compared_including_pad_and_without_overflow():
    # native_edge8_b with LI set to its visible samples only (7 x 5 x 3 = 105) instead of the
    # 192 its four 4 x 4 blocks need: LI[0] is at 369, FL at 342, the data at 869.
    raw = vector("native_edge8_b")
    visible = put(put(raw[: 869 + 105], 369, _d(105, 10)), 342, _d(869 + 105, 12))
    assert refusal(visible) == ("E_LENGTH", "segment", 869, "/segments/image[0]/data")
    # A grid whose sample length (101 x 101 blocks of 9999 x 9999, 256 bands of 16 bits, about
    # 5.2e14 octets, beyond 2**48) against LI 4: the comparison is made on the whole product and
    # refuses at the data start (HL 404 plus a 3759-octet subheader). The case below is the one
    # that tells an exact comparison from a truncated one.
    image = image_sh(
        NROWS=b"01000000",
        NCOLS=b"01000000",
        ABPP=b"16",
        NBPP=b"16",
        NBANDS=b"0",
        XBANDS=b"00256",
        BANDS=BAND * 256,
        NBPR=b"0101",
        NBPC=b"0101",
        NPPBH=b"9999",
        NPPBV=b"9999",
    )
    assert refusal(container(images=[(image, b"\x00" * 4)])) == (
        "E_LENGTH",
        "segment",
        4163,
        "/segments/image[0]/data",
    )


def test_li_is_compared_exactly_when_the_true_length_wraps_to_it_modulo_2_32_or_2_48():
    # 61 x 10 blocks of 6605 x 533 (NCOLS 402905 = 61 x 6605, NROWS 5330 = 10 x 533, both
    # minimally covered), one band of 16 bits: 61 * 10 * 6605 * 533 * 2 = 4,294,967,300 octets,
    # which is 2**32 + 4. Against LI 4 a comparison truncated to 32 bits would see equal lengths;
    # the exact one refuses at the data start, 843 (HL 404 plus a 439-octet subheader).
    assert 61 * 10 * 6605 * 533 * 2 == 2**32 + 4
    image = image_sh(
        NROWS=b"00005330",
        NCOLS=b"00402905",
        ABPP=b"16",
        NBPP=b"16",
        NBPR=b"0061",
        NBPC=b"0010",
        NPPBH=b"6605",
        NPPBV=b"0533",
    )
    assert refusal(container(images=[(image, b"\x00" * 4)])) == (
        "E_LENGTH",
        "segment",
        843,
        "/segments/image[0]/data",
    )
    # The same past 2**48: 81 x 569 blocks of 7395 x 1613 (NCOLS 598995 = 81 x 7395, NROWS
    # 917797 = 569 x 1613, 46,089 blocks), 256 bands of 16 bits, is 2**48 + 65,024 octets, and LI
    # is 65,024. The data starts at 4163 (HL 404 plus the 3759-octet 256-band subheader).
    assert 81 * 569 * 7395 * 1613 * 256 * 2 == 2**48 + 65_024
    image = image_sh(
        NROWS=b"00917797",
        NCOLS=b"00598995",
        ABPP=b"16",
        NBPP=b"16",
        NBANDS=b"0",
        XBANDS=b"00256",
        BANDS=BAND * 256,
        NBPR=b"0081",
        NBPC=b"0569",
        NPPBH=b"7395",
        NPPBV=b"1613",
    )
    assert refusal(container(images=[(image, b"\x00" * 65_024)])) == (
        "E_LENGTH",
        "segment",
        4163,
        "/segments/image[0]/data",
    )


def test_sample_index_is_a_bijection_onto_the_payload_in_every_mode():
    for nbpr, nbpc, width, height, bands in itertools.product((1, 2, 3), repeat=5):
        total = nbpr * nbpc * width * height * bands
        for mode in "BPRS":
            found = [
                nc.sample_index(mode, nbpr, nbpc, width, height, bands, x, y, b)
                for b in range(bands)
                for y in range(nbpc * height)
                for x in range(nbpr * width)
            ]
            assert len(found) == total and set(found) == set(range(total))


def test_sample_index_reads_the_literal_payloads_and_addresses_pad():
    for mode, payload in LIT_PAYLOADS.items():
        octets = bytes.fromhex(payload)
        read = tuple(
            octets[nc.sample_index(mode, 3, 2, 2, 3, 2, x, y, b)]
            for b in range(2)
            for y in range(4)
            for x in range(5)
        )
        assert read == LIT_SAMPLES
        # Column 5 and row 4 are pad inside the physical grid: addressable here, refused by a
        # window request.
        assert octets[nc.sample_index(mode, 3, 2, 2, 3, 2, 5, 0, 0)] == 0xFF
        assert octets[nc.sample_index(mode, 3, 2, 2, 3, 2, 0, 5, 1)] == 0xFF


@pytest.mark.parametrize(
    "arguments",
    [
        ("B", 3, 2, 2, 3, 2, 6, 0, 0),
        ("B", 3, 2, 2, 3, 2, 0, 6, 0),
        ("B", 3, 2, 2, 3, 2, 0, 0, 2),
        ("B", 3, 2, 0, 3, 2, 0, 0, 0),
        ("B", 0, 2, 2, 3, 2, 0, 0, 0),
        ("Q", 3, 2, 2, 3, 2, 0, 0, 0),
        (b"B", 3, 2, 2, 3, 2, 0, 0, 0),
        ("B", 3, 2, 2, 3, 2, True, 0, 0),
        ("B", 3, 2, 2, 3, 2, 1.0, 0, 0),
        ("B", 3, 2, 2, 3, 2, -1, 0, 0),
        ("S", 3, 2, 2, 3, 0, 0, 0, 0),
    ],
)
def test_sample_index_refuses_every_argument_outside_the_native_layout(arguments):
    with pytest.raises(nc.NsifError) as caught:
        nc.sample_index(*arguments)
    error = caught.value
    assert (error.code, error.stage, error.offset, error.path, error.explanation) == (
        "E_FIELD",
        "pixels",
        None,
        "/window",
        "sample index argument outside the native layout",
    )


@pytest.mark.parametrize("stem", READING_STEMS)
def test_the_decoder_takes_every_sample_from_sample_index(stem):
    found = parse(image_bearing(stem))
    image = found.images[0]
    octets = image.nbpp // 8
    start = image.segment.data.offset
    layout = (image.imode, image.nbpr, image.nbpc, image.block_width, image.block_height)
    read = tuple(
        int.from_bytes(
            found.raw[start + octets * nc.sample_index(*layout, image.band_count, x, y, b) :][
                :octets
            ],
            "big",
        )
        for b in range(image.band_count)
        for y in range(image.nrows)
        for x in range(image.ncols)
    )
    assert full(found, storage=True).values() == read


def test_a_lut_is_metadata_and_the_window_returns_its_indexes():
    found = parse(vector("native_lut3"))
    image = found.images[0]
    assert (image.irep, image.bands[0].irepband, image.bands[0].nluts, image.bands[0].neluts) == (
        "RGB/LUT",
        "LU",
        3,
        4,
    )
    assert image.bands[0].lut == nc.Slice(798, 12) and image.segment.data.offset == 860
    assert found.raw[798:810].hex() == "0055aaff" + "ffaa5500" + "0a141e28"
    assert full(found).values() == (0, 1, 2, 3) and full(found).dtype == "uint8"
    assert found.diagnostics == ()


# --------------------------------------------------------------------------- GDAL's reading
#
# GDAL's reading of every image-bearing vector, taken by `gates/nsif_gdal_reading.py` where GDAL
# is installed and tracked under `independent/`. GDAL returns storage integers, so the decoder's
# storage view is compared with it, modulo 2^NBPP (GDAL prints 16-bit SI as signed); the
# interpreted view is compared only where interpretation is the identity (INT, ABPP = NBPP).

#: The band data type GDAL names for each native cell (8-bit SI is read as unsigned Byte).
GDAL_TYPES = {("INT", 8): "Byte", ("SI", 8): "Byte", ("INT", 16): "UInt16", ("SI", 16): "Int16"}

READING_KEYS = [
    "file",
    "bytes",
    "sha256",
    "gdal_data_type",
    "size",
    "band_count",
    "storage_band_major",
]


def reading(stem: str) -> dict:
    return json.loads((INDEPENDENT / f"{stem}.gdal.json").read_text())


def test_there_is_one_reading_per_image_bearing_vector():
    on_disk = sorted(p.name[: -len(".gdal.json")] for p in INDEPENDENT.glob("*.gdal.json"))
    expected = sorted([*KIT_IMAGE_STEMS, *(p.stem for p in VECTORS.glob("*.ntf"))])
    assert on_disk == expected and len(on_disk) == 58
    assert sorted(KIT_IMAGE_STEMS) == sorted(KIT_SAMPLES)


def test_the_reading_record_states_what_the_reading_is():
    record = json.loads((INDEPENDENT / "gdal_reading.json").read_text())
    assert list(record) == [
        "gdal_version",
        "commands",
        "file_paths",
        "gdallocationinfo_input",
        "environment",
        "date",
        "statement",
    ]
    assert record["commands"] == [
        ["gdalinfo", "--version"],
        ["gdalinfo", "-json", "<file>"],
        ["gdallocationinfo", "-valonly", "<file>"],
    ]
    assert record["environment"] == {"GDAL_PAM_ENABLED": "NO"}
    assert record["statement"] == (
        "storage integers and corner numbers only; synthetic vectors; unpinned Homebrew build; "
        "not a header, label, negative-vector or seam oracle"
    )
    assert record["gdal_version"].startswith("GDAL 3.")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["date"])


@pytest.mark.parametrize("stem", READING_STEMS)
def test_the_decoder_agrees_with_gdals_recorded_reading(stem):
    recorded = reading(stem)
    octets = image_bearing(stem)
    location = f"{stem}.ntf" if stem in KIT_SAMPLES else f"vectors/{stem}.ntf"
    assert recorded["file"] == location
    assert (recorded["bytes"], recorded["sha256"]) == (
        len(octets),
        hashlib.sha256(octets).hexdigest(),
    )
    found = parse(octets)
    image = found.images[0]
    assert recorded["size"] == [image.ncols, image.nrows]
    assert recorded["band_count"] == image.band_count
    assert recorded["gdal_data_type"] == GDAL_TYPES[(image.pvtype, image.nbpp)]
    modulus = 1 << image.nbpp
    assert full(found, storage=True).values() == tuple(
        v % modulus for v in recorded["storage_band_major"]
    )
    if image.pvtype == "INT" and image.abpp == image.nbpp:
        assert full(found).values() == tuple(recorded["storage_band_major"])
    extra = {"native_lut3": ["color_table"]}
    for geo in (
        "geo_dms",
        "native_geo_g_northup",
        "native_geo_g_southup",
        "native_geo_d_northup",
        "native_geo_d_southup",
    ):
        extra[geo] = ["geo_transform", "corners"]
    assert list(recorded) == READING_KEYS + extra.get(stem, [])


def test_the_lut_tables_are_gdals_palette_in_file_order():
    found = parse(vector("native_lut3"))
    lut = found.images[0].bands[0].lut
    neluts = found.images[0].bands[0].neluts
    tables = [found.raw[lut.offset + k * neluts : lut.offset + (k + 1) * neluts] for k in range(3)]
    palette = [[tables[0][i], tables[1][i], tables[2][i], 255] for i in range(neluts)]
    assert palette == reading("native_lut3")["color_table"]
    assert palette == [[0, 255, 10, 255], [85, 170, 20, 255], [170, 85, 30, 255], [255, 0, 40, 255]]


def test_the_decoder_tests_need_no_gdal():
    source = pathlib.Path(__file__).read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"subprocess", "o" + "sgeo", "shutil", "os"}
    assert ("o" + "sgeo") not in source
