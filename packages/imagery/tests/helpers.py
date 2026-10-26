"""Test inputs for the host: the kit's vectors as the installed adapter packages them, checked
against the kit's digests, and an independent minimal NSIF builder with literal-offset mutators
for every input the kit does not have.

The builder is written from the engineering kit's grammar alone; it imports neither the adapter
nor the kit's generator, so an expectation computed from what it builds is not the code under
test's own. Its defaults are the kit's field values, so with no argument it rebuilds
`mono_nsif101` octet for octet, which the static tests hold.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import uuid

import synapse_cdm

VECTORS = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "stanag4545"

#: The 17 digests of the kit's `fixtures/expected.json`, by file name.
KIT_SHA256 = {
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

TOP_LEVEL = (
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
MALFORMED = (
    "bad_file_length.ntf",
    "truncated.ntf",
    "trailing.ntf",
    "bad_count.ntf",
    "unsupported_stype.ntf",
)

#: The samples of expected.json, band-major, for the vectors that decode.
KIT_SAMPLES = {
    "mono": [0, 64, 128, 255],
    "modes": list(range(1, 17)) + list(range(21, 37)) + list(range(41, 57)),
    "uint16": [0, 256, 4095, 65535],
}


def vector(name: str) -> bytes:
    """A kit vector from the installed adapter's fixture tree, digest-checked; a missing or
    altered file fails the test, never skips it."""
    if name in TOP_LEVEL:
        path = VECTORS / name
    elif name in MALFORMED:
        path = VECTORS / "malformed" / name
    elif name == "header_only.ntf":
        path = VECTORS / "context" / name
    else:
        raise KeyError(name)
    octets = path.read_bytes()
    assert hashlib.sha256(octets).hexdigest() == KIT_SHA256[name], name
    return octets


def sha(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


# --------------------------------------------------------------------------- literal offsets
# The one-image layout of the kit's vectors: a 360-octet prefix, a directory ending at HL 404,
# then the image subheader at 404.

FL, HL, NUMI, LISH, LI = 342, 354, 360, 363, 369
FILE_ENCRYP = 296
FTITLE = (39, 119)
ONAME = (300, 324)
IID1 = (406, 416)
IDATIM = (416, 430)
TGTID = (430, 447)
IID2 = (447, 527)
IMAGE_ENCRYP = 694
ISORCE = (695, 737)
NROWS, NCOLS = 737, 745
NICOM, IC = 776, 777
FILE_BLOCK, IMAGE_BLOCK = 119, 527

#: Field offsets inside a 167-octet security block, and its width.
SECURITY_FIELDS = (
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
SECURITY_WIDTH = 167
_FIELD = {name: (offset, width) for name, offset, width in SECURITY_FIELDS}


def set_field(octets: bytes, offset: int, value: bytes | str) -> bytes:
    """`octets` with `value` written at `offset`, same length."""
    data = value.encode("ascii") if isinstance(value, str) else value
    assert offset + len(data) <= len(octets)
    return octets[:offset] + data + octets[offset + len(data) :]


def with_security_field(octets: bytes, scope: str, name: str, value: bytes | str) -> bytes:
    """One field of the file (119) or image (527) block of the one-image layout, space-padded."""
    base = {"file": FILE_BLOCK, "image": IMAGE_BLOCK}[scope]
    offset, width = _FIELD[name]
    data = value.encode("ascii") if isinstance(value, str) else value
    assert len(data) <= width
    return set_field(octets, base + offset, data.ljust(width, b" "))


def _bump(octets: bytes, offset: int, width: int, delta: int) -> bytes:
    value = int(octets[offset : offset + width]) + delta
    return set_field(octets, offset, f"{value:0{width}d}")


def with_ic(octets: bytes, ic: str, comrat: bytes = b"00.0") -> bytes:
    """The one-image layout with IC at 777 set to `ic`. Every code but NC and NM is followed by
    a four-octet COMRAT, so it is inserted and LISH (363, 6 digits) and FL (342, 12 digits) are
    raised by 4."""
    out = set_field(octets, IC, ic)
    if ic in ("NC", "NM"):
        return out
    out = out[: IC + 2] + comrat + out[IC + 2 :]
    out = _bump(out, LISH, 6, 4)
    return _bump(out, FL, 12, 4)


def with_encryp(octets: bytes, scope: str, byte: bytes = b"1") -> bytes:
    return set_field(octets, {"file": FILE_ENCRYP, "image": IMAGE_ENCRYP}[scope], byte)


def fifo(path: pathlib.Path) -> pathlib.Path:
    os.mkfifo(path)
    return path


# --------------------------------------------------------------------------- the builder


def a(value: str | bytes, width: int) -> bytes:
    data = value.encode("ascii") if isinstance(value, str) else value
    assert len(data) <= width, (value, width)
    return data.ljust(width, b" ")


def d(value: int, width: int) -> bytes:
    text = f"{value:0{width}d}".encode("ascii")
    assert len(text) == width
    return text


def security(clas: str = "U", **fields: str | bytes) -> bytes:
    """A 167-octet security block: CLAS and any other field by its name, the rest spaces."""
    values = {"CLAS": clas, **fields}
    out = b"".join(a(values.get(name, ""), width) for name, _, width in SECURITY_FIELDS)
    assert len(out) == SECURITY_WIDTH
    return out


def area(tres: bytes = b"", overflow: int = 0) -> bytes:
    """An extension area: a 5-digit length, then (when not empty) a 3-digit overflow number and
    the TRE octets."""
    if not tres and not overflow:
        return b"00000"
    return d(3 + len(tres), 5) + d(overflow, 3) + tres


def tre(tag: str, payload: bytes) -> bytes:
    return a(tag, 6) + d(len(payload), 5) + payload


def image(
    *,
    rows: int = 2,
    cols: int = 2,
    data: bytes | None = None,
    bands: int = 1,
    nbpp: int = 8,
    abpp: int | None = None,
    pvtype: str = "INT",
    irep: str | None = None,
    icat: str = "VIS",
    pjust: str = "R",
    icords: str = " ",
    igeolo: str = "",
    comments: tuple[bytes, ...] = (),
    ic: str = "NC",
    comrat: bytes = b"00.0",
    imode: str = "B",
    block: tuple[int, int] | None = None,
    idlvl: int = 1,
    ialvl: int = 0,
    iloc: bytes = b"0000000000",
    iid1: str | bytes = "SCFIX0001",
    idatim: str | bytes = "20261004120000",
    tgtid: str | bytes = "",
    iid2: str | bytes = "SYNTHETIC TEST ONLY",
    isorce: str | bytes = "SYNTHETIC",
    sec: bytes | None = None,
    tres: bytes = b"",
    irepband: bytes = b"M ",
    irepbands: tuple[bytes, ...] | None = None,
    luts: tuple[bytes, ...] = (),
) -> tuple[bytes, bytes]:
    """One image segment (subheader, data) in the grammar's cursor order. With no argument it is
    the kit's 2x2 8-bit mono image whose samples are 0, 64, 128, 255. `irepbands` gives each band
    its own descriptor; `luts` gives every band the same lookup tables (NLUTS of them, each
    NELUTS octets, contiguous)."""
    if icords != " " and not igeolo:
        raise ValueError("a non-blank ICORDS needs its 60-octet IGEOLO")
    width, height = (cols, rows) if block is None else block
    nbpr, nbpc = -(-cols // width), -(-rows // height)
    if data is None:
        size = nbpr * nbpc * width * height * bands * (nbpp // 8)
        data = (b"\x00\x40\x80\xff" * (size // 4 + 1))[:size]
    descriptors = irepbands if irepbands is not None else (irepband,) * bands
    assert len(descriptors) == bands
    tables = b""
    if luts:
        assert len({len(table) for table in luts}) == 1
        tables = d(len(luts[0]), 5) + b"".join(luts)
    out = b"IM" + a(iid1, 10) + a(idatim, 14) + a(tgtid, 17) + a(iid2, 80)
    out += sec if sec is not None else security()
    out += b"0" + a(isorce, 42) + d(rows, 8) + d(cols, 8) + a(pvtype, 3)
    out += a(irep if irep is not None else ("MONO" if bands == 1 else "MULTI"), 8)
    out += a(icat, 8) + d(nbpp if abpp is None else abpp, 2) + a(pjust, 1)
    out += a(icords, 1) + (a(igeolo, 60) if icords != " " else b"")
    out += d(len(comments), 1) + b"".join(a(comment, 80) for comment in comments)
    out += a(ic, 2) + (b"" if ic in ("NC", "NM") else comrat)
    out += d(bands, 1) if bands < 10 else b"0" + d(bands, 5)
    out += b"".join(
        a(descriptor, 2) + b" " * 6 + b"N" + b" " * 3 + d(len(luts), 1) + tables
        for descriptor in descriptors
    )
    out += b"0" + a(imode, 1) + d(nbpr, 4) + d(nbpc, 4) + d(width, 4) + d(height, 4)
    out += d(nbpp, 2) + d(idlvl, 3) + d(ialvl, 3) + iloc + b"1.0 "
    out += b"00000" + area(tres)
    return out, data


def graphic(*, sdlvl: int = 2, salvl: int = 1, data: bytes = b"CGM", sec: bytes | None = None):
    out = b"SY" + a("SCGRAPH01", 10) + a("SYNTHETIC GRAPHIC", 20)
    out += sec if sec is not None else security()
    out += b"0" + b"C" + b"0" * 13 + d(sdlvl, 3) + d(salvl, 3) + b"0" * 10 + b"0" * 10
    out += b"C" + b"0" * 10 + b"00" + b"00000"
    return out, data


def text(
    *,
    payload: bytes = b"PLAIN TEXT",
    txtfmt: str = "STA",
    title: str | bytes = "SYNTHETIC TEXT",
    sec: bytes | None = None,
    tres: bytes = b"",
):
    out = b"TE" + a("TXT001", 7) + b"000" + b"20261004120000" + a(title, 80)
    out += sec if sec is not None else security()
    out += b"0" + a(txtfmt, 3) + area(tres)
    return out, payload


def des(*, desid: str = "SCDES", payload: bytes = b"OPAQUE", sec: bytes | None = None):
    out = b"DE" + a(desid, 25) + b"01" + (sec if sec is not None else security()) + b"0000"
    return out, payload


def build_nsif(
    images=(),
    *,
    graphics=(),
    texts=(),
    des_segments=(),
    magic: bytes = b"NSIF01.01",
    clevel: bytes = b"03",
    ostaid: str = "SCFIX",
    fdt: str | bytes = "20261004120000",
    ftitle: str | bytes = "SYNTHETIC ENGINEERING VECTOR",
    file_security: bytes | None = None,
    oname: str | bytes = "SYNAPSECOMMAND TEST",
) -> bytes:
    """A whole container: the 360-octet prefix, the directory, then the segments in the
    grammar's order (images, graphics, text, DES). Each segment is a (subheader, data) pair."""
    directory = d(len(images), 3) + b"".join(d(len(s), 6) + d(len(p), 10) for s, p in images)
    directory += d(len(graphics), 3) + b"".join(d(len(s), 4) + d(len(p), 6) for s, p in graphics)
    directory += b"000"
    directory += d(len(texts), 3) + b"".join(d(len(s), 4) + d(len(p), 5) for s, p in texts)
    directory += d(len(des_segments), 3)
    directory += b"".join(d(len(s), 4) + d(len(p), 9) for s, p in des_segments)
    directory += b"000" + b"00000" + b"00000"
    body = b"".join(s + p for s, p in (*images, *graphics, *texts, *des_segments))
    head = magic + clevel + b"BF01" + a(ostaid, 10) + a(fdt, 14) + a(ftitle, 80)
    head += file_security if file_security is not None else security()
    head += b"00000" + b"00000" + b"0" + bytes(3) + a(oname, 24) + a("", 18)
    assert len(head) == 342
    header_length = 360 + len(directory)
    return head + d(header_length + len(body), 12) + d(header_length, 6) + directory + body


# --------------------------------------------------------------------------- ruled formulas
# The identifier formulas of the rulings, written again here from their text, so a test that
# states an id does not take it from the code under test.

_URL = uuid.NAMESPACE_URL


def _cj(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def ruled_record_id(tenant, dataset, synthetic, digest, revision, state) -> str:
    namespace = uuid.uuid5(_URL, "urn:synapsecommand:imagery:record")
    parts = ["sc-imagery-record/1", tenant, dataset, synthetic, digest, revision, state]
    return str(uuid.uuid5(namespace, _cj(parts)))


def ruled_attempt_id(
    tenant, dataset, synthetic, digest, size, revision, state, code, stage, path
) -> str:
    namespace = uuid.uuid5(_URL, "urn:synapsecommand:imagery:record")
    parts = ["sc-imagery-attempt/1", tenant, dataset, synthetic, digest, size, revision]
    return str(uuid.uuid5(namespace, _cj(parts + [state, code, stage, path])))


def ruled_asset_id(tenant, digest) -> str:
    namespace = uuid.uuid5(_URL, "urn:synapsecommand:imagery:asset")
    return str(uuid.uuid5(namespace, _cj(["sc-imagery-original/1", tenant, digest])))


def ruled_tenant_dir(tenant) -> str:
    return str(uuid.uuid5(uuid.uuid5(_URL, "urn:synapsecommand:imagery:tenant"), tenant))


def ruled_export_id(tenant, recipe_sha256, output_sha256) -> str:
    namespace = uuid.uuid5(_URL, "urn:synapsecommand:imagery:export")
    return str(
        uuid.uuid5(namespace, _cj(["sc-imagery-export/1", tenant, recipe_sha256, output_sha256]))
    )


def ruled_dedup_id(tenant, dataset, synthetic, digest, revision) -> str:
    parts = ["sc-imagery-dedup/1", tenant, dataset, synthetic, digest, revision]
    return hashlib.sha256(_cj(parts).encode("ascii")).hexdigest()


def store_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())
