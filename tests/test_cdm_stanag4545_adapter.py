"""The STANAG 4545 NSIF/NITF imagery adapter, `adapters/stanag4545.py`: the class and its guard,
the context, the argument rules, `detect`, `validate_source`, identity, time, the product Entity,
its attributes, the security labels and assessment, the product and footprint residuals, the
footprint PlanObjects, provenance, TRANSFORMS and MAPPINGS, the two output caps, the manifest
declaration, the packaged fixture tree with its twins and goldens, and the golden wrapper for the
context vector.

Every expectation is a literal: an identifier, offset, text or record written out by hand from the
field widths of the specification and the mapping rules, a digest copied from the kit's
`expected.json`, or a value computed here by an independent route (a digest with `hashlib`, a size
with `json.dumps`). Mutated containers are built with the packaged builder's kit helpers (`image`,
`container`, `sec`, `a`, `d`), which write fields in the specification's order and know nothing of
the parser, or by patching a literal offset of a kit vector. Package-only: every path is anchored
on the imported package and nothing is written outside `tmp_path`.

THE TWO KIT LAYOUTS THE MUTATIONS USE
-------------------------------------
`mono_nsif101.ntf` (847 octets): header to HL 404, the file security block at 119, ENCRYP 296,
FBKGC 297, FL 342; one image subheader at 404 (IID1 406, IDATIM 416, TGTID 430, IID2 447, the image
security block at 527, ISORCE 695, ICORDS 775, no IGEOLO) and four data octets at 843.
`geo_dms.ntf` (907 octets) is the same with ICORDS `G` and sixty IGEOLO octets at 776, so the image
subheader is 499 octets and every image field after 775 moves by sixty.
"""

from __future__ import annotations

import ast
import base64
import copy
import dataclasses
import hashlib
import inspect
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

import synapse_cdm
from synapse_cdm import adapter as adapter_module
from synapse_cdm import harness, ids, lossless, manifests, times, version
from synapse_cdm.adapter import Adapter, InputTooDeep, InputTooLarge
from synapse_cdm.adapters import nsif_codec, nsif_geometry
from synapse_cdm.adapters import stanag4545 as module
from synapse_cdm.adapters.geojson import AsOf
from synapse_cdm.adapters.nsif_codec import Limits, NsifError, NsifInputTooDeep, NsifInputTooLarge
from synapse_cdm.adapters.stanag4545 import (
    Stanag4545Adapter,
    Stanag4545Context,
    assess_security,
    security_labels,
)
from synapse_cdm.manifest import (
    ClaimStatus,
    LimitKind,
    MaturityLevel,
    Residual,
    UnknownFields,
    WireBinding,
    limitation_text,
)
from tests import observation_support as support

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "stanag4545"
LIMITS = nsif_codec.CORE1_LIMITS
T = Stanag4545Adapter.TRANSFORMS

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

#: The eleven translatable kit vectors at the top level, by stem.
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
MALFORMED = (
    "bad_count.ntf",
    "bad_file_length.ntf",
    "trailing.ntf",
    "truncated.ntf",
    "unsupported_stype.ntf",
)

#: Each kit negative's one `validate_source` string: the code, offset and path `expected.json`
#: and the specification assign, and the parser's fixed explanation for that check.
KIT_REFUSALS = {
    "bad_count.ntf": "E_DIGITS @byte 360 /file_header/NUMI: an octet outside 0x30-0x39",
    "bad_file_length.ntf": "E_LENGTH @byte 342 /file_header/FL: FL differs from the input length",
    "trailing.ntf": "E_LENGTH @byte 342 /file_header/FL: FL differs from the input length",
    "truncated.ntf": "E_LENGTH @byte 342 /file_header/FL: FL differs from the input length",
    "unsupported_stype.ntf": "E_PROFILE @byte 11 /file_header/STYPE: STYPE is not BF01",
}

#: The source-tuple key every NSIF 01.01 single-image kit vector shares (61 characters).
KEY = '["NSIF","01.01","SCFIX     ","20261004120000",["SCFIX0001 "]]'
#: The three product identities, `ids.derive` over that key under `STANAG4545:default`.
ENTITY_NSIF101 = "10b992a0-7c4d-5e74-a4dd-5e36f553bb00"
ENTITY_NITF210 = "97b51da7-0fcc-5782-adcb-f3666b21d792"
ENTITY_NSIF100 = "699ab728-0830-5c1b-9473-18f9b01fc1fc"
FOOTPRINT_GEO_DMS = "76031395-0afa-5184-a0b8-4b6f9f8ebf3e"
STAMP = "2026-10-04T12:00:00.000Z"

#: Offset and width of each of the sixteen fields inside a 167-octet security block.
SEC_FIELDS = {
    "CLAS": (0, 1),
    "CLSY": (1, 2),
    "CODE": (3, 11),
    "CTLH": (14, 2),
    "REL": (16, 20),
    "DCTP": (36, 2),
    "DCDT": (38, 8),
    "DCXM": (46, 4),
    "DG": (50, 1),
    "DGDT": (51, 8),
    "CLTX": (59, 43),
    "CAPT": (102, 1),
    "CAUT": (103, 40),
    "CRSN": (143, 1),
    "SRDT": (144, 8),
    "CTLN": (152, 15),
}
FILE_SEC, IMAGE_SEC = 119, 527
BLANK_LABEL_FIELDS = {name: "" for name in SEC_FIELDS} | {"CLAS": "U"}

GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"


def _build_fixtures_module():
    """The packaged builder, loaded from SOURCE and never from bytecode.

    `tests/test_cdm_generator_loading.py` holds every loader to that by poisoning a
    `__pycache__` entry: a `.pyc` is revalidated on the source's mtime in whole seconds and its
    size, so an edit reverted inside one second leaves a cache that validates against a file it
    was not compiled from. `FIXTURES` is read at call time so that test can point it at a copy.
    """
    path = FIXTURES / "spec" / "build_fixtures.py"
    built = types.ModuleType("stanag4545_build_fixtures")
    built.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), built.__dict__)
    return built


KIT = _build_fixtures_module()

EXERCISE_CONTEXT = Stanag4545Context(
    dataset_namespace="exercise",
    product_key="EXERCISE-HEADER-ONLY-0001",
    asset_ref="exercise-asset-0001",
    verified_sha256=hashlib.sha256(
        (FIXTURES / "context" / "header_only.ntf").read_bytes()
    ).hexdigest(),
)


class ExerciseContextAdapter(Stanag4545Adapter):
    """The golden wrapper for `context/`: the shipped class under an explicit exercise context.

    Abstract, so it is never registered, and outside the package, so the harness accepts
    `--fixtures` for it. It overrides only the packaged-fixture hook; a direct construction keeps
    the default context.
    """

    abstract = True

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        return cls(clock=clock, synthetic=synthetic, context=EXERCISE_CONTEXT)


def vector(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def twin(stem: str) -> dict:
    return json.loads((FIXTURES / f"{stem}.parsed.json").read_text())


def adapter(**options) -> Stanag4545Adapter:
    return Stanag4545Adapter(clock=times.frozen_clock(), **options)


def dump(objects) -> list[dict]:
    return [item.model_dump(mode="json") for item in objects]


def translate(raw, **options) -> list[dict]:
    return dump(adapter(**options).to_cdm(raw))


def patch(raw: bytes, offset: int, value: bytes) -> bytes:
    out = bytearray(raw)
    out[offset : offset + len(value)] = value
    return bytes(out)


def sec_patch(raw: bytes, block: int, name: str, value: bytes) -> bytes:
    offset, width = SEC_FIELDS[name]
    return patch(raw, block + offset, value.ljust(width, b" ")[:width])


def refusal(call, *args) -> NsifError:
    with pytest.raises(NsifError) as caught:
        call(*args)
    return caught.value


def coded(error: NsifError) -> tuple:
    return (error.code, error.stage, error.offset, error.path)


def residual(objects: list[dict], index: int = 0) -> dict:
    return objects[index]["residual"]["data"]["stanag4545"]


def graphic_sh(sdlvl: int, salvl: int) -> bytes:
    """One graphic subheader, no extension area, fields in the specification's order."""
    a, d = KIT.a, KIT.d
    return (
        b"SY"
        + a("SCGRAPH01", 10)
        + a("SYNTHETIC GRAPHIC", 20)
        + KIT.sec()
        + b"0"
        + b"C"
        + bytes(13).replace(b"\x00", b"0")
        + d(sdlvl, 3)
        + d(salvl, 3)
        + b"0000000000"
        + b"0000000000"
        + b"C"
        + b"0000000000"
        + b"00"
        + b"00000"
    )


def des_sh(desid: str, oflw: tuple[str, int] | None = None) -> bytes:
    a, d = KIT.a, KIT.d
    out = b"DE" + a(desid, 25) + b"01" + KIT.sec()
    if oflw is not None:
        out += a(oflw[0], 6) + d(oflw[1], 3)
    return out + b"0000"


def res_sh() -> bytes:
    return b"RE" + KIT.a("SCRES", 25) + b"01" + KIT.sec() + b"0000"


def mono_with(**fields) -> bytes:
    """`mono_nsif101` with header or image fields replaced at their literal offsets."""
    offsets = {"OSTAID": 15, "FDT": 25, "FTITLE": 39, "IID1": 406, "IDATIM": 416, "TGTID": 430}
    raw = vector("mono_nsif101.ntf")
    for name, value in fields.items():
        raw = patch(raw, offsets[name], value)
    return raw


def geo_with(**fields) -> bytes:
    offsets = {"FDT": 25, "IID1": 406, "IDATIM": 416, "IGEOLO": 776, "IID2": 447, "FTITLE": 39}
    raw = vector("geo_dms.ntf")
    for name, value in fields.items():
        raw = patch(raw, offsets[name], value)
    return raw


# --------------------------------------------------------------------------- the class


def test_the_class_declares_its_identity_and_the_guard_chain():
    cls = Stanag4545Adapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "stanag4545",
        "1.0.0",
        "ingest",
        "STANAG4545",
    )
    assert "to_cdm" in cls.__dict__
    assert cls.to_cdm.__input_bounded__ is True
    assert cls.to_cdm.__wrapped__.__input_bounded__ is True
    assert cls.to_cdm.__wrapped__.__wrapped__.__name__ == "to_cdm"
    assert "fixture_instance" not in cls.__dict__
    assert cls.from_cdm is Adapter.from_cdm
    with pytest.raises(NotImplementedError):
        Stanag4545Adapter().from_cdm([])
    assert harness.packaged_fixtures(cls).name == "stanag4545"
    assert adapter_module.discover()["stanag4545"] is cls
    assert cls.__module__ == "synapse_cdm.adapters.stanag4545"
    assert module.PROFILE == "SC4545-CORE-1"
    assert module.FORMAT_NAME == "NSIF/NITF imagery"
    assert module.FORMAT_VERSION == "SC4545-CORE-1; STANAG 4545 Ed 2 target"
    assert module.SYSTEM == "STANAG4545"
    assert module.PROFILE_REVISION == 1


def test_the_public_names_are_exactly_the_ruled_list():
    assert sorted(module.__all__) == sorted(
        [
            "Stanag4545Adapter",
            "Stanag4545Context",
            "security_labels",
            "assess_security",
            "PROFILE",
            "FORMAT_NAME",
            "FORMAT_VERSION",
            "SYSTEM",
            "PROFILE_REVISION",
            "Container",
            "Limits",
            "CORE1_LIMITS",
            "NsifError",
            "NsifInputTooLarge",
            "NsifInputTooDeep",
            "Diagnostic",
            "DIAGNOSTIC_CODES",
            "parse_container",
            "decode_nc_window",
            "SampleWindow",
        ]
    )
    # The re-exports are the codec's own objects, and `Limits` is the codec's, not the manifest's.
    for name in ("Container", "Limits", "NsifError", "parse_container", "decode_nc_window"):
        assert getattr(module, name) is getattr(nsif_codec, name)


_IMPORT_AUDIT = """
import enum, json, sys
import synapse_cdm, synapse_cdm.adapter, synapse_cdm.models, synapse_cdm.manifest
import synapse_cdm.adapters.geojson
from synapse_cdm import enums, models
fresh = [n for n in ("synapse_cdm.adapters.stanag4545", "synapse_cdm.adapters.nsif_codec",
         "synapse_cdm.adapters.nsif_geometry") if n not in sys.modules]
def vocabulary():
    found = {n: [m.value for m in e] for n, e in sorted(vars(enums).items())
             if isinstance(e, type) and issubclass(e, enum.Enum)}
    return [repr(models.KINDS), found]
before = vocabulary()
events = []
def hook(event, args):
    if event.startswith(("socket.", "urllib.", "subprocess.")) or event == "open":
        events.append([event, str(args[0]) if args else ""])
sys.addaudithook(hook)
import synapse_cdm.adapters.stanag4545
loaded = [n for n in fresh if n in sys.modules]
bad = [e for e in events if e[0] != "open" or not e[1].endswith((".py", ".pyc", ".so", ".pyd"))]
print(json.dumps({"fresh": fresh, "loaded": loaded, "events": len(events), "bad": bad,
                  "same": before == vocabulary()}))
"""


def test_importing_the_adapter_opens_only_modules_and_changes_no_vocabulary():
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _IMPORT_AUDIT],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    names = [
        "synapse_cdm.adapters.stanag4545",
        "synapse_cdm.adapters.nsif_codec",
        "synapse_cdm.adapters.nsif_geometry",
    ]
    # Each of the three was imported after the hook, so the audit saw everything they did.
    assert found["fresh"] == names and found["loaded"] == names
    assert found["events"] > 0
    assert found["bad"] == []
    assert found["same"] is True


# --------------------------------------------------------------------------- construction


def test_the_constructor_checks_synthetic_and_context_exactly():
    assert Stanag4545Adapter()._synthetic is True
    assert Stanag4545Adapter().context == Stanag4545Context()
    assert Stanag4545Adapter.fixture_instance(clock=times.frozen_clock()).context == (
        Stanag4545Context()
    )
    for value in (None, "true", 1, 0):
        with pytest.raises(TypeError):
            Stanag4545Adapter(synthetic=value)
    with pytest.raises(TypeError):
        Stanag4545Adapter(context={"dataset_namespace": "d"})
    nine = Stanag4545Adapter(context=Stanag4545Context(dataset_namespace="d9"))
    assert nine.namespace == "STANAG4545:d9"
    parameters = inspect.signature(Stanag4545Adapter).parameters
    assert list(parameters) == ["clock", "synthetic", "context"]
    assert parameters["synthetic"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["context"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["synthetic"].default is True and parameters["context"].default is None
    live = translate(vector("geo_dms.ntf"), synthetic=False)
    assert [item["source"]["synthetic"] for item in live] == [False, False]
    assert [item["source"]["synthetic"] for item in translate(vector("geo_dms.ntf"))] == [True] * 2


def test_the_context_defaults_and_is_frozen():
    assert dataclasses.astuple(Stanag4545Context()) == ("default", None, None, None, None)
    context = Stanag4545Context()
    for name in ("dataset_namespace", "product_key", "as_of", "asset_ref", "verified_sha256"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(context, name, None)
    assert [f.name for f in dataclasses.fields(Stanag4545Context)] == [
        "dataset_namespace",
        "product_key",
        "as_of",
        "asset_ref",
        "verified_sha256",
    ]


@pytest.mark.parametrize(
    "options, error",
    [
        ({"dataset_namespace": ""}, ValueError),
        ({"dataset_namespace": " "}, ValueError),
        ({"dataset_namespace": "a|b"}, ValueError),
        ({"dataset_namespace": "x" * 129}, ValueError),
        ({"dataset_namespace": "é"}, ValueError),
        ({"dataset_namespace": 5}, TypeError),
        ({"product_key": ""}, ValueError),
        ({"product_key": "a|b"}, ValueError),
        ({"verified_sha256": "AB" * 32}, ValueError),
        ({"verified_sha256": "ab" * 31}, ValueError),
        ({"as_of": {"instant": "2026-01-02T03:04:05Z", "basis": "exercise context"}}, TypeError),
        ({"asset_ref": ""}, ValueError),
        ({"asset_ref": " "}, ValueError),
        ({"asset_ref": "x" * 257}, ValueError),
    ],
)
def test_the_context_refuses_each_malformed_field(options, error):
    with pytest.raises(error):
        Stanag4545Context(**options)


def test_the_context_accepts_its_boundary_values():
    Stanag4545Context(dataset_namespace="x" * 128)
    Stanag4545Context(product_key="k")
    Stanag4545Context(verified_sha256="ab" * 32)
    Stanag4545Context(asset_ref="a|b")
    Stanag4545Context(asset_ref="x" * 256)
    Stanag4545Context(as_of=AsOf("2026-01-02T03:04:05Z", "exercise context instant"))


# --------------------------------------------------------------------------- the argument

OVER = 16_777_217


@pytest.mark.parametrize("kind", ["bytes", "bytearray", "memoryview", "str"])
def test_one_octet_over_the_bound_is_a_coded_refusal_that_is_also_input_too_large(kind):
    raw = {
        "bytes": lambda: b"\xff" * OVER,
        "bytearray": lambda: bytearray(OVER),
        "memoryview": lambda: memoryview(bytes(OVER)),
        "str": lambda: "é" * (OVER // 2) + "x",
    }[kind]()
    error = refusal(adapter().to_cdm, raw)
    assert isinstance(error, NsifInputTooLarge) and isinstance(error, InputTooLarge)
    assert coded(error) == ("E_LIMIT", "input", None, "/input")
    assert "16777216" in str(error) and "16777217" in str(error)
    assert adapter().validate_source(raw) == [
        "E_LIMIT @byte - /input: input is 16777217 octets; the limit is 16777216"
    ]


def test_at_the_bound_the_guard_is_silent_and_the_parser_refuses():
    error = refusal(adapter().to_cdm, b"\xff" * 16_777_216)
    assert not isinstance(error, InputTooLarge)
    assert coded(error) == ("E_MAGIC", "header", 0, "/file_header/FHDR")
    error = refusal(adapter().to_cdm, "x" * 16_777_216)
    assert not isinstance(error, InputTooLarge)
    assert coded(error) == ("E_FIELD", "input", None, "/input")


def test_parse_container_refuses_the_same_oversize_input_the_same_way():
    error = refusal(nsif_codec.parse_container, b"\x00" * OVER, LIMITS)
    assert type(error) is NsifInputTooLarge
    assert coded(error) == ("E_LIMIT", "input", None, "/input")


class _Bytes(bytes):
    pass


class _Dict(dict):
    pass


@pytest.mark.parametrize(
    "make",
    [
        lambda raw: bytearray(raw),
        lambda raw: memoryview(raw),
        lambda raw: raw.decode("latin-1"),
        lambda raw: _Bytes(raw),
        lambda raw: _Dict({"profile": "SC4545-CORE-1", "wire_b64": ""}),
        lambda raw: [raw],
        lambda raw: None,
        lambda raw: 42,
    ],
    ids=[
        "bytearray",
        "memoryview",
        "str",
        "bytes-subclass",
        "dict-subclass",
        "list",
        "None",
        "int",
    ],
)
def test_every_other_argument_type_is_refused_without_coercion(make):
    raw = make(vector("mono_nsif101.ntf"))
    error = refusal(adapter().to_cdm, raw)
    assert coded(error) == ("E_FIELD", "input", None, "/input")
    assert adapter().validate_source(raw) == [
        "E_FIELD @byte - /input: the input is neither bytes nor a twin"
    ]


def test_the_twin_depth_bound_admits_depth_four_shapes_and_refuses_five():
    depth4 = {"a": {"b": {"c": {"d": 1}}}}
    depth5 = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    error = refusal(adapter().to_cdm, depth4)
    assert not isinstance(error, InputTooDeep)
    assert coded(error) == ("E_FIELD", "input", None, "/twin")
    error = refusal(adapter().to_cdm, depth5)
    assert isinstance(error, NsifInputTooDeep) and isinstance(error, InputTooDeep)
    assert coded(error) == ("E_LIMIT", "input", None, "/twin")
    error = refusal(nsif_codec.decode_twin, depth5, LIMITS)
    assert coded(error) == ("E_LIMIT", "input", None, "/twin")
    assert adapter().validate_source(depth5) == [
        "E_LIMIT @byte - /twin: twin nests deeper than 4 containers"
    ]
    # Behind the guard the SDK's own wrapper measures the same depth and speaks its own class.
    with pytest.raises(InputTooDeep) as caught:
        Stanag4545Adapter.to_cdm.__wrapped__(adapter(), depth5)
    assert type(caught.value) is InputTooDeep
    assert "max_depth = 4" in str(caught.value)
    wire = {"profile": "SC4545-CORE-1", "wire_b64": [[["x"]]]}
    assert coded(refusal(adapter().to_cdm, wire)) == ("E_FIELD", "input", None, "/twin/wire_b64")


def test_a_self_referential_twin_is_refused_at_once():
    loop: dict = {}
    loop["self"] = loop
    wide: dict = {}
    for k in range(3000):
        wide[f"k{k}"] = wide
    for raw in (loop, wide):
        error = refusal(adapter().to_cdm, raw)
        assert isinstance(error, InputTooDeep)
        assert coded(error) == ("E_LIMIT", "input", None, "/twin")


def test_payloads_without_a_supported_magic_never_reach_the_sdk_text_decode():
    nested = b"[" * 5 + b"]" * 5
    for raw in (nested, nested.decode("ascii").encode("utf-16")):
        assert coded(refusal(adapter().to_cdm, raw)) == (
            "E_MAGIC",
            "header",
            0,
            "/file_header/FHDR",
        )
    assert coded(refusal(adapter().to_cdm, b"NSIF01.0")) == (
        "E_LENGTH",
        "header",
        0,
        "/file_header/FHDR",
    )
    assert coded(refusal(adapter().to_cdm, "\ud800abc")) == ("E_FIELD", "input", None, "/input")
    released = memoryview(b"NSIF01.01")
    released.release()
    assert coded(refusal(adapter().to_cdm, released)) == ("E_FIELD", "input", None, "/input")


def test_the_sdk_wrapper_stays_reachable_behind_the_guard():
    with pytest.raises(InputTooLarge) as caught:
        Stanag4545Adapter.to_cdm.__wrapped__(adapter(), b"\xff" * OVER)
    assert type(caught.value) is InputTooLarge
    assert not issubclass(NsifError, (InputTooLarge, InputTooDeep))
    assert issubclass(NsifInputTooLarge, NsifError) and issubclass(NsifInputTooLarge, InputTooLarge)
    assert issubclass(NsifInputTooDeep, NsifError) and issubclass(NsifInputTooDeep, InputTooDeep)


def test_a_nitf_02_00_head_is_not_this_adapter_s_and_is_refused():
    raw = patch(vector("mono_nsif101.ntf"), 0, b"NITF02.00")
    assert adapter().detect(raw) is False
    assert coded(refusal(adapter().to_cdm, raw)) == ("E_MAGIC", "header", 0, "/file_header/FHDR")


# --------------------------------------------------------------------------- the twin


def _twin_of(raw: bytes, **changes) -> dict:
    document = {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(raw).decode("ascii")}
    document.update(changes)
    return document


def test_a_twin_in_either_key_order_translates_like_its_container():
    raw = vector("geo_dms.ntf")
    reversed_twin = {"wire_b64": base64.b64encode(raw).decode("ascii"), "profile": "SC4545-CORE-1"}
    assert translate(reversed_twin) == translate(raw)


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"extra": 1}, ("E_FIELD", "/twin")),
        ({"profile": "SC4545-CORE-2"}, ("E_PROFILE", "/twin/profile")),
        ({"wire_b64": "TlNJ RjAx"}, ("E_FIELD", "/twin/wire_b64")),
        ({"wire_b64": "TlNJRjAx\n"}, ("E_FIELD", "/twin/wire_b64")),
        ({"wire_b64": "TlNJRjA"}, ("E_FIELD", "/twin/wire_b64")),
        ({"wire_b64": "AB=="}, ("E_FIELD", "/twin/wire_b64")),
        ({"wire_b64": "-_8="}, ("E_FIELD", "/twin/wire_b64")),
        ({"wire_b64": "TlNJéjAx"}, ("E_FIELD", "/twin/wire_b64")),
    ],
)
def test_twin_shape_and_encoding_refusals_reach_the_caller_from_to_cdm(changes, expected):
    document = _twin_of(vector("mono_nsif101.ntf"), **changes)
    error = refusal(adapter().to_cdm, document)
    assert (error.code, error.stage, error.offset, error.path) == (
        expected[0],
        "input",
        None,
        expected[1],
    )
    assert adapter().validate_source(document) == [str(error)]


def test_a_twin_without_a_member_is_refused():
    for missing in ("profile", "wire_b64"):
        document = _twin_of(vector("mono_nsif101.ntf"))
        del document[missing]
        assert coded(refusal(adapter().to_cdm, document)) == ("E_FIELD", "input", None, "/twin")


def test_a_non_canonical_twin_is_refused_so_the_ledger_can_hold_identity():
    raw = vector("mono_nsif101.ntf")
    canonical = base64.b64encode(raw).decode("ascii")
    # 847 octets leave one octet, 0xFF, in the last group: `/w==`, whose last character carries
    # four pad bits. `/x==` sets one of them and decodes to the same octets.
    assert canonical.endswith("/w==")
    loose = canonical[:-4] + "/x=="
    assert base64.b64decode(loose) == raw
    document = {"profile": "SC4545-CORE-1", "wire_b64": loose}
    assert coded(refusal(adapter().to_cdm, document)) == (
        "E_FIELD",
        "input",
        None,
        "/twin/wire_b64",
    )


def test_the_twin_caps_are_read_at_call_time(monkeypatch):
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(twin_chars=8))
    error = refusal(adapter().to_cdm, {"profile": "SC4545-CORE-1", "wire_b64": "A" * 12})
    assert coded(error) == ("E_LIMIT", "input", None, "/twin/wire_b64")
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(input_bytes=5))
    error = refusal(adapter().to_cdm, {"profile": "SC4545-CORE-1", "wire_b64": "AAAAAAAA"})
    assert coded(error) == ("E_LIMIT", "input", None, "/twin/wire_b64")
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(input_bytes=6))
    error = refusal(adapter().to_cdm, {"profile": "SC4545-CORE-1", "wire_b64": "AAAAAAAA"})
    assert coded(error) == ("E_LENGTH", "header", 0, "/file_header/FHDR")


# --------------------------------------------------------------------------- detect


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"NSIF01.01", True),
        (b"NSIF01.00rest", True),
        (b"NITF02.10", True),
        (b"NSIF01.0", None),
        (b"", None),
        (b"NITF02.00", False),
        (b"\x00" * 9, False),
        (bytearray(b"NSIF01.01"), None),
        ("NSIF01.01", None),
        (42, None),
        (None, None),
        ({"a": 1}, None),
        ({"profile": "SC4545-CORE-1", "wire_b64": "TlNJRjAxLjAx"}, True),
        ({"wire_b64": "TlNJRjAxLjAx", "profile": "SC4545-CORE-1"}, True),
        ({"profile": "SC4545-CORE-1", "wire_b64": "TklURjAyLjAwWFla"}, False),
        ({"profile": "SC4545-CORE-1", "wire_b64": "TlNJRjAxLjA"}, None),
        ({"profile": "SC4545-CORE-1", "wire_b64": "TlNJRjAxLjA="}, None),
        ({"profile": "SC4545-CORE-2", "wire_b64": "TlNJRjAxLjAx"}, None),
        ({"profile": "SC4545-CORE-1", "wire_b64": 7}, None),
        ({"profile": "SC4545-CORE-1", "wire_b64": "TlNJRjAxLjAx", "x": 1}, None),
        (_Dict({"profile": "SC4545-CORE-1", "wire_b64": "TlNJRjAxLjAx"}), None),
        (_Bytes(b"NSIF01.01"), None),
    ],
)
def test_detect_answers_from_the_first_nine_octets(raw, expected):
    assert adapter().detect(raw) is expected


def test_detect_reads_no_size_cap_and_keeps_no_state():
    assert adapter().detect(b"NSIF01.01" + bytes(OVER)) is True
    instance = adapter()
    before = dict(vars(instance))
    instance.detect(b"NITF02.10")
    assert vars(instance) == before


# --------------------------------------------------------------------------- validate_source


def test_validate_source_is_empty_for_every_ok_kit_vector_and_twin():
    for stem in TOP_LEVEL:
        assert adapter().validate_source(vector(f"{stem}.ntf")) == [], stem
        assert adapter().validate_source(twin(stem)) == [], stem
    assert adapter().validate_source(vector("context/header_only.ntf")) == []
    header_twin = json.loads((FIXTURES / "context" / "header_only.parsed.json").read_text())
    assert adapter().validate_source(header_twin) == []


@pytest.mark.parametrize("name", MALFORMED)
def test_validate_source_gives_one_string_for_each_kit_negative(name):
    raw = vector(f"malformed/{name}")
    assert adapter().validate_source(raw) == [KIT_REFUSALS[name]]
    assert str(refusal(adapter().to_cdm, raw)) == KIT_REFUSALS[name]


def test_validate_source_lists_only_the_violations_of_the_profile():
    malformed_date = mono_with(FDT=b"2026100412000Z")
    assert adapter().validate_source(malformed_date) == [
        "DATE_MALFORMED @byte 25 /file_header/FDT: the date is not fourteen digits of a UTC date "
        "and time"
    ]
    assert adapter().validate_source(mono_with(FDT=b" " * 14)) == []
    bad_minute = geo_with(IGEOLO=b"486000N" + GEO[7:].encode())
    assert adapter().validate_source(bad_minute) == [
        "GEOMETRY_INVALID @byte 776 /segments/image[0]/IGEOLO: corner value is outside its valid "
        "range"
    ]
    # One image and one graphic: HL 414 (the directory gains a 10-octet graphic entry), the
    # 439-octet image subheader and 4 data octets, so the graphic subheader starts at 857 and its
    # SDLVL 2+10+20+167+1+1+13 = 214 octets into it, at 1071.
    duplicate = KIT.container([KIT.image()], others=[("S", graphic_sh(1, 0), b"abc")])
    assert adapter().validate_source(duplicate) == [
        "COMPOSITION_DUPLICATE_LEVEL @byte 1071 /segments/graphic[0]/SDLVL: the display level is "
        "already used by an earlier image or graphic"
    ]
    # Statuses and limitations of the profile are not violations: a compressed image, a UTM
    # corner set, an unknown TRE and a non-printable title all validate empty.
    compressed = _compressed()
    assert [d.code for d in nsif_codec.parse_container(compressed, LIMITS).diagnostics] == [
        "COMPRESSION_NOT_ENABLED"
    ]
    assert adapter().validate_source(compressed) == []
    utm = patch(vector("geo_dms.ntf"), 775, b"U")
    assert adapter().validate_source(utm) == []
    assert adapter().validate_source(vector("unknown_duplicate_tre.ntf")) == []
    assert adapter().validate_source(mono_with(FTITLE=b"\xff")) == []


def test_validate_source_answers_coded_refusals_only_and_lets_any_other_error_through(
    monkeypatch,
):
    # A coded refusal is NsifError, itself a ValueError, so an except clause widened to
    # ValueError would turn a defect into a result string; the parser is replaced to raise both.
    def coded(octets, limits):
        raise NsifError("E_FIELD", "header", 9, "/file_header/CLEVEL", "a stand-in refusal")

    def defect(octets, limits):
        raise ValueError("not a coded refusal")

    raw = vector("mono_nsif101.ntf")
    monkeypatch.setattr(module, "parse_container", coded)
    assert adapter().validate_source(raw) == [
        "E_FIELD @byte 9 /file_header/CLEVEL: a stand-in refusal"
    ]
    monkeypatch.setattr(module, "parse_container", defect)
    with pytest.raises(ValueError) as caught:
        adapter().validate_source(raw)
    assert type(caught.value) is ValueError
    assert caught.value.args == ("not a coded refusal",)


def _compressed() -> bytes:
    """`mono_nsif101` with IC `C8` at 777 and the COMRAT `1.00` a compressed code requires after
    it, so the image subheader is four octets longer."""
    sh, pixels = KIT.image()
    return KIT.container([(sh[:373] + b"C8" + b"1.00" + sh[375:], pixels)])


def test_compressed_images_are_inventoried_and_still_translate():
    compressed = _compressed()
    objects = translate(compressed)
    image = objects[0]["attributes"]["stanag4545"]["images"][0]
    assert (image["compression"], image["pixel_status"]) == ("C8", "unsupported")
    assert objects[0]["attributes"]["stanag4545"]["diagnostics"] == [
        {
            "code": "COMPRESSION_NOT_ENABLED",
            "stage": "pixels",
            "offset": 777,
            "path": "/segments/image[0]/IC",
            "message": "no pixel path is enabled for this compression code in this deployment",
        }
    ]


# --------------------------------------------------------------------------- order


def test_a_parse_error_comes_before_a_context_error():
    raw = vector("context/header_only.ntf")[:-1]
    error = refusal(adapter().to_cdm, raw)
    assert coded(error) == ("E_LENGTH", "header", 342, "/file_header/FL")


def test_the_product_comes_first_and_the_footprints_follow_in_image_order():
    for stem in TOP_LEVEL:
        objects = translate(vector(f"{stem}.ntf"))
        assert objects[0]["object_kind"] == "entity"
        assert [o["object_kind"] for o in objects[1:]] == ["plan_object"] * (len(objects) - 1)
        assert len(objects) == (2 if stem == "geo_dms" else 1), stem
    two = KIT.container([KIT.image(geo=GEO), KIT.image(geo=GEO)])
    objects = translate(two)
    assert [(o["object_kind"], o["source"]["record_index"]) for o in objects] == [
        ("entity", 0),
        ("plan_object", 0),
        ("plan_object", 1),
    ]


def test_to_cdm_keeps_no_state_between_calls():
    instance = adapter()
    before = dict(vars(instance))
    first = dump(instance.to_cdm(vector("geo_dms.ntf")))
    instance.to_cdm(vector("image_and_text.ntf"))
    assert dump(instance.to_cdm(vector("geo_dms.ntf"))) == first
    assert vars(instance) == before
    assert set(vars(instance)) == {"_clock", "_synthetic", "_context"}


# --------------------------------------------------------------------------- identity


def test_the_product_identities_are_the_source_tuple_identities():
    assert translate(vector("mono_nsif101.ntf"))[0]["entity_id"] == ENTITY_NSIF101
    assert translate(vector("mono_nitf210.ntf"))[0]["entity_id"] == ENTITY_NITF210
    assert translate(vector("mono_nsif100.ntf"))[0]["entity_id"] == ENTITY_NSIF100
    assert len(KEY) == 61
    objects = translate(vector("geo_dms.ntf"))
    assert objects[0]["entity_id"] == ENTITY_NSIF101
    assert objects[0]["source_ids"] == [{"system": "STANAG4545:default", "external_id": KEY}]
    footprint_key = (
        '["[\\"NSIF\\",\\"01.01\\",\\"SCFIX     \\",\\"20261004120000\\",[\\"SCFIX0001 \\"]]",0]'
    )
    assert len(footprint_key) == 77
    assert objects[1]["source_ids"] == [
        {"system": "STANAG4545:default", "external_id": footprint_key}
    ]
    assert objects[1]["object_id"] == FOOTPRINT_GEO_DMS
    assert FOOTPRINT_GEO_DMS == str(
        ids.derive("STANAG4545:default", footprint_key, kind="imagery-footprint")
    )
    assert objects[0]["attributes"]["stanag4545"]["product_key"] == KEY


def test_header_only_needs_a_product_key_while_parsing_succeeds():
    raw = vector("context/header_only.ntf")
    error = refusal(adapter().to_cdm, raw)
    assert coded(error) == ("E_CONTEXT", "cdm", None, "/context/product_key")
    assert nsif_codec.parse_container(raw, LIMITS).images == ()
    objects = translate(raw, context=Stanag4545Context(product_key="EXERCISE-HEADER-ONLY-0001"))
    assert len(objects) == 1
    assert objects[0]["entity_id"] == str(
        ids.derive("STANAG4545:default", "EXERCISE-HEADER-ONLY-0001", kind="imagery-product")
    )


@pytest.mark.parametrize(
    "fields",
    [{"OSTAID": b" " * 10}, {"IID1": b" " * 10}, {"OSTAID": b"SCFIX\x80    "}, {"IID1": b"\xff"}],
    ids=["blank-ostaid", "blank-iid1", "non-ascii-ostaid", "non-ascii-iid1"],
)
def test_an_incomplete_source_tuple_needs_a_product_key(fields):
    raw = mono_with(**fields)
    assert coded(refusal(adapter().to_cdm, raw)) == (
        "E_CONTEXT",
        "cdm",
        None,
        "/context/product_key",
    )
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001")
    assert translate(raw, context=context)[0]["source_ids"][0]["external_id"] == (
        "EXERCISE-CASES-0001"
    )


def test_an_unknown_fdt_makes_the_source_tuple_unavailable():
    raw = mono_with(FDT=b" " * 14)
    assert coded(refusal(adapter().to_cdm, raw)) == (
        "E_CONTEXT",
        "cdm",
        None,
        "/context/product_key",
    )
    keyed = Stanag4545Context(product_key="EXERCISE-CASES-0001")
    assert coded(refusal(adapter(context=keyed).to_cdm, raw)) == (
        "E_CONTEXT",
        "cdm",
        None,
        "/context/as_of",
    )
    as_of = AsOf("2026-01-02T03:04:05Z", "exercise context instant")
    full = Stanag4545Context(product_key="EXERCISE-CASES-0001", as_of=as_of)
    assert len(translate(raw, context=full)) == 1


def test_the_namespace_moves_every_identifier():
    objects = translate(vector("geo_dms.ntf"), context=Stanag4545Context(dataset_namespace="d9"))
    assert objects[0]["entity_id"] == str(ids.derive("STANAG4545:d9", KEY, kind="imagery-product"))
    assert objects[0]["entity_id"] != ENTITY_NSIF101
    assert objects[1]["object_id"] != FOOTPRINT_GEO_DMS
    assert {item["source_ids"][0]["system"] for item in objects} == {"STANAG4545:d9"}
    assert residual(objects, 1)["product"]["system"] == "STANAG4545:d9"


def test_a_supplied_product_key_is_used_verbatim():
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001")
    objects = translate(vector("geo_dms.ntf"), context=context)
    assert objects[0]["source"]["original_id"] == "EXERCISE-CASES-0001"
    assert objects[1]["source"]["original_id"] == "EXERCISE-CASES-0001"
    assert objects[1]["source_ids"][0]["external_id"] == '["EXERCISE-CASES-0001",0]'
    assert objects[1]["object_id"] == str(
        ids.derive("STANAG4545:default", '["EXERCISE-CASES-0001",0]', kind="imagery-footprint")
    )


# --------------------------------------------------------------------------- time


def test_valid_from_and_the_capture_times_come_from_fdt_and_idatim():
    objects = translate(vector("mono_nsif101.ntf"))
    record = objects[0]["attributes"]["stanag4545"]
    assert objects[0]["valid_from"] == STAMP
    assert record["product_time"] == STAMP
    assert record["images"][0]["capture_time"] == STAMP
    assert objects[0]["source"]["observed_at"] is None
    footprint = translate(vector("geo_dms.ntf"))[1]
    assert footprint["validity"] == {
        "observed_at": STAMP,
        "valid_from": None,
        "valid_to": None,
        "effective": None,
    }
    assert footprint["source"]["observed_at"] == STAMP
    assert footprint["expires_at"] is None


def test_an_unknown_fdt_falls_back_to_as_of_with_its_basis_recorded():
    as_of = AsOf("2026-01-02T03:04:05Z", "exercise context instant")
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001", as_of=as_of)
    objects = translate(geo_with(FDT=b" " * 14), context=context)
    assert objects[0]["valid_from"] == "2026-01-02T03:04:05.000Z"
    assert objects[0]["attributes"]["stanag4545"]["product_time"] is None
    assert objects[0]["source"]["transformations"] == [
        T["ASCII display trimming"],
        T["UTC reformatting"],
        T["date fallback"] + " Basis: exercise context instant",
        T["integer conversion"],
    ]
    # A valid FDT always wins over a supplied as_of, which is then unused and unrecorded.
    with_valid = translate(vector("geo_dms.ntf"), context=context)
    assert with_valid[0]["valid_from"] == STAMP
    assert T["date fallback"] not in " ".join(with_valid[0]["source"]["transformations"])


def test_a_blank_idatim_gives_no_capture_time_and_no_validity():
    objects = translate(geo_with(IDATIM=b" " * 14))
    assert objects[0]["attributes"]["stanag4545"]["images"][0]["capture_time"] is None
    assert objects[1]["validity"] is None
    assert objects[1]["source"]["observed_at"] is None
    assert objects[1]["source"]["transformations"][:2] == [
        T["ASCII display trimming"],
        T["IGEOLO corner coordinates"],
    ]


def test_no_clock_is_read():
    def broken():
        raise AssertionError("the clock was read")

    objects = dump(Stanag4545Adapter(clock=broken).to_cdm(vector("geo_dms.ntf")))
    later = times.frozen_clock(times.parse("2031-01-01T00:00:00Z"))
    assert objects == dump(Stanag4545Adapter(clock=later).to_cdm(vector("geo_dms.ntf")))
    assert objects == translate(vector("geo_dms.ntf"))


@pytest.mark.parametrize(
    "fdt, stamp",
    [
        (b"00010101000000", "0001-01-01T00:00:00.000Z"),
        (b"99991231235959", "9999-12-31T23:59:59.000Z"),
    ],
)
def test_the_extreme_valid_dates_render_with_four_year_digits(fdt, stamp):
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001")
    objects = translate(mono_with(FDT=fdt), context=context)
    assert objects[0]["valid_from"] == stamp
    assert objects[0]["attributes"]["stanag4545"]["product_time"] == stamp


def test_no_event_is_emitted():
    for stem in TOP_LEVEL:
        kinds = {o["object_kind"] for o in translate(vector(f"{stem}.ntf"))}
        assert kinds <= {"entity", "plan_object"}


# --------------------------------------------------------------------------- the product


def test_the_product_entity_carries_only_the_fixed_fields():
    for stem in TOP_LEVEL:
        product = translate(vector(f"{stem}.ntf"))[0]
        assert product["entity_type"] == "OVERLAY_OBJECT"
        assert product["affiliation"] == "UNKNOWN"
        for name in (
            "symbol",
            "position",
            "kinematics",
            "confidence",
            "valid_to",
            "quality",
            "status",
            "integrity",
        ):
            assert product[name] is None, (stem, name)
        assert product["ontology_types"] == []
        assert list(product["attributes"]) == ["stanag4545"]
        assert product["residual"]["namespace"] == "NSIF/NITF imagery"


def test_a_mutated_tgtid_changes_only_residual_text():
    before = translate(vector("geo_dms.ntf"))
    after = translate(patch(vector("geo_dms.ntf"), 430, b"EXERCISE TGT 01  "))
    assert len(before) == len(after)
    for old, new in zip(before, after):
        assert old["object_kind"] == new["object_kind"]
        old_rest = {k: v for k, v in old.items() if k != "residual"}
        new_rest = {k: v for k, v in new.items() if k != "residual"}
        assert old_rest == new_rest
    assert residual(after)["segments"][0]["fields"]["TGTID"] == {
        "offset": 430,
        "length": 17,
        "text": "EXERCISE TGT 01",
    }
    assert residual(before)["segments"][0]["fields"]["TGTID"]["text"] == ""


def test_the_attributes_record_of_mono_nsif101():
    product = adapter().to_cdm(vector("mono_nsif101.ntf"))[0]
    record = product.model_dump()["attributes"]
    assert record == {
        "stanag4545": {
            "profile": "SC4545-CORE-1",
            "wire_signature": "NSIF01.01",
            "product_key": KEY,
            "product_time": STAMP,
            "asset_ref": None,
            "images": [
                {
                    "index": 0,
                    "iid1": "SCFIX0001",
                    "capture_time": STAMP,
                    "rows": 2,
                    "columns": 2,
                    "bands": 1,
                    "pvtype": "INT",
                    "abpp": 8,
                    "nbpp": 8,
                    "compression": "NC",
                    "mode": "B",
                    "pixel_status": "native_supported",
                    "geometry_status": "absent",
                    "composition_status": "segment_only",
                }
            ],
            "security_status": "declared_unclassified",
            "diagnostics": [],
        }
    }
    # Key order is the record's own, in memory; goldens are written with sorted keys.
    inner = record["stanag4545"]
    assert list(inner) == [
        "profile",
        "wire_signature",
        "product_key",
        "product_time",
        "asset_ref",
        "images",
        "security_status",
        "diagnostics",
    ]
    assert list(inner["images"][0]) == [
        "index",
        "iid1",
        "capture_time",
        "rows",
        "columns",
        "bands",
        "pvtype",
        "abpp",
        "nbpp",
        "compression",
        "mode",
        "pixel_status",
        "geometry_status",
        "composition_status",
    ]


def test_the_wire_signature_and_the_profile_are_recorded_separately():
    for name, signature in (
        ("mono_nsif101.ntf", "NSIF01.01"),
        ("mono_nsif100.ntf", "NSIF01.00"),
        ("mono_nitf210.ntf", "NITF02.10"),
    ):
        product = translate(vector(name))[0]
        assert product["attributes"]["stanag4545"]["wire_signature"] == signature
        assert product["attributes"]["stanag4545"]["profile"] == "SC4545-CORE-1"
        assert product["source"]["format_version"] == "SC4545-CORE-1; STANAG 4545 Ed 2 target"
        assert product["source"]["format_name"] == "NSIF/NITF imagery"


def test_no_output_key_names_an_edition_or_a_national_profile():
    pattern = re.compile(r"edition|jbp|national|nato|nitfs", re.I)

    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    for stem in TOP_LEVEL:
        found = {key for key in keys(translate(vector(f"{stem}.ntf"))) if pattern.search(key)}
        assert found == set(), stem


def test_composition_status_is_the_container_s_own_on_every_image_record():
    clean = KIT.container([KIT.image()], others=[("S", graphic_sh(2, 1), b"abc")])
    objects = translate(clean)
    record = objects[0]["attributes"]["stanag4545"]
    assert record["images"][0]["composition_status"] == "segment_only"
    assert record["diagnostics"] == []
    duplicate = KIT.container([KIT.image()], others=[("S", graphic_sh(1, 1), b"abc")])
    record = translate(duplicate)[0]["attributes"]["stanag4545"]
    assert record["images"][0]["composition_status"] == "unavailable"
    assert [(d["code"], d["path"]) for d in record["diagnostics"]] == [
        ("COMPOSITION_DUPLICATE_LEVEL", "/segments/graphic[0]/SDLVL")
    ]


def test_an_unsupported_image_keeps_its_record_and_gets_no_footprint():
    utm = patch(vector("geo_dms.ntf"), 775, b"U")
    objects = translate(utm)
    assert len(objects) == 1
    image = objects[0]["attributes"]["stanag4545"]["images"][0]
    assert image["geometry_status"] == "unsupported"
    assert objects[0]["attributes"]["stanag4545"]["diagnostics"] == [
        {
            "code": "GEOMETRY_UNSUPPORTED",
            "stage": "geometry",
            "offset": 775,
            "path": "/segments/image[0]/ICORDS",
            "message": "ICORDS names a coordinate system this profile preserves but does not project",
        }
    ]


# --------------------------------------------------------------------------- labels


def test_the_file_label_of_mono_nsif101():
    labels = residual(translate(vector("mono_nsif101.ntf")))["security"]["labels"]
    assert labels == [
        {
            "scope": "file",
            "index": None,
            "offset": 119,
            "length": 167,
            "fields": BLANK_LABEL_FIELDS,
            "uninterpreted": [],
        },
        {
            "scope": "image",
            "index": 0,
            "offset": 527,
            "length": 167,
            "fields": BLANK_LABEL_FIELDS,
            "uninterpreted": [],
        },
    ]
    assert list(labels[0]["fields"]) == list(SEC_FIELDS)
    assert list(labels[0]) == ["scope", "index", "offset", "length", "fields", "uninterpreted"]


@pytest.mark.parametrize("scope, block", [("file", FILE_SEC), ("image", IMAGE_SEC)])
@pytest.mark.parametrize("name", list(SEC_FIELDS))
def test_every_label_field_is_preserved_on_the_product_and_the_footprint(scope, block, name):
    width = SEC_FIELDS[name][1]
    value = "R" if name == "CLAS" else "Z" * width
    objects = translate(sec_patch(vector("geo_dms.ntf"), block, name, value.encode()))
    assert len(objects) == 2
    for item in objects:
        labels = item["residual"]["data"]["stanag4545"]["security"]["labels"]
        label = next(entry for entry in labels if entry["scope"] == scope)
        assert label["fields"][name] == value
        assert label["uninterpreted"] == []


def test_a_label_field_that_is_not_printable_is_uninterpreted_and_unresolved():
    raw = sec_patch(vector("geo_dms.ntf"), IMAGE_SEC, "CTLN", b"\xff\xfe")
    objects = translate(raw)
    label = residual(objects)["security"]["labels"][1]
    assert label["fields"]["CTLN"] is None
    assert label["uninterpreted"] == ["CTLN"]
    assert residual(objects)["security"]["assessment"]["reasons"] == ["LABEL_FIELD_UNINTERPRETED"]
    assert residual(objects, 1)["security"]["labels"][1] == label


def _decodable_runs(node, raw: bytes, threshold: int) -> list[str]:
    found = []
    if isinstance(node, dict):
        for value in node.values():
            found += _decodable_runs(value, raw, threshold)
    elif isinstance(node, list):
        for value in node:
            found += _decodable_runs(value, raw, threshold)
    elif isinstance(node, str) and len(node) >= threshold:
        try:
            decoded = base64.b64decode(node, validate=True)
        except ValueError:
            return found
        if decoded and decoded in raw:
            found.append(node)
    return found


def test_the_source_octets_appear_once_and_only_as_wire_b64():
    banned = {"b64", "base64", "raw"}

    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    for stem in TOP_LEVEL:
        raw = vector(f"{stem}.ntf")
        objects = translate(raw)
        product = residual(objects)
        assert _decodable_runs(objects, raw, 16) == [product["wire_b64"]], stem
        assert banned.isdisjoint(keys(product["security"]))
        assert banned.isdisjoint(keys(product["segments"]))
        for index in range(1, len(objects)):
            assert "wire_b64" not in json.dumps(objects[index])


# --------------------------------------------------------------------------- assessment


def _assessment(raw: bytes) -> dict:
    objects = translate(raw)
    found = residual(objects)["security"]["assessment"]
    assert objects[0]["attributes"]["stanag4545"]["security_status"] == found["status"]
    for index in range(1, len(objects)):
        assert residual(objects, index)["security"]["assessment"] == found
    assert assess_security(nsif_codec.parse_container(raw, LIMITS)) == found
    return found


def _text_sec() -> int:
    raw = vector("image_and_text.ntf")
    return nsif_codec.parse_container(raw, LIMITS).texts[0].security.slice.offset


def _rows():
    base = vector("geo_dms.ntf")
    text = vector("image_and_text.ntf")
    tre = vector("unknown_duplicate_tre.ntf")
    text_sec = _text_sec()

    def m(raw, block, name, value):
        return sec_patch(raw, block, name, value)

    return [
        ("geo_dms unchanged", base, "declared_unclassified", [], ["U"], True),
        (
            "file CLAS R",
            m(base, FILE_SEC, "CLAS", b"R"),
            "labelled",
            ["CLAS_NOT_U"],
            ["R", "U"],
            False,
        ),
        (
            "image CLAS R",
            m(base, IMAGE_SEC, "CLAS", b"R"),
            "labelled",
            ["CLAS_NOT_U"],
            ["R", "U"],
            False,
        ),
        (
            "file and image CLAS S",
            m(m(base, FILE_SEC, "CLAS", b"S"), IMAGE_SEC, "CLAS", b"S"),
            "labelled",
            ["CLAS_NOT_U"],
            ["S"],
            True,
        ),
        (
            "file CLAS blank",
            m(base, FILE_SEC, "CLAS", b" "),
            "unresolved",
            ["CLAS_UNRECOGNISED"],
            ["", "U"],
            False,
        ),
        (
            "image CLAS X",
            m(base, IMAGE_SEC, "CLAS", b"X"),
            "unresolved",
            ["CLAS_UNRECOGNISED"],
            ["U", "X"],
            False,
        ),
        (
            "file CLAS u",
            m(base, FILE_SEC, "CLAS", b"u"),
            "unresolved",
            ["CLAS_UNRECOGNISED"],
            ["U", "u"],
            False,
        ),
        (
            "file REL",
            m(base, FILE_SEC, "REL", b"XA XB"),
            "labelled",
            ["RESTRICTIVE_CAVEAT"],
            ["U"],
            True,
        ),
        (
            "image CODE",
            m(base, IMAGE_SEC, "CODE", b"ALPHA"),
            "labelled",
            ["RESTRICTIVE_CAVEAT"],
            ["U"],
            True,
        ),
        (
            "file CTLH",
            m(base, FILE_SEC, "CTLH", b"XX"),
            "labelled",
            ["RESTRICTIVE_CAVEAT"],
            ["U"],
            True,
        ),
        (
            "file CLSY only",
            m(base, FILE_SEC, "CLSY", b"XN"),
            "labelled",
            ["MIXED_CLASSIFICATION_SYSTEM"],
            ["U"],
            True,
        ),
        (
            "file and image CLSY",
            m(m(base, FILE_SEC, "CLSY", b"XN"), IMAGE_SEC, "CLSY", b"XN"),
            "declared_unclassified",
            [],
            ["U"],
            True,
        ),
        (
            "file CLTX",
            m(base, FILE_SEC, "CLTX", b"EXERCISE TEXT"),
            "declared_unclassified",
            [],
            ["U"],
            True,
        ),
        (
            "image DG and DGDT",
            m(m(base, IMAGE_SEC, "DG", b"S"), IMAGE_SEC, "DGDT", b"20300101"),
            "declared_unclassified",
            [],
            ["U"],
            True,
        ),
        (
            "image CTLN not printable",
            m(base, IMAGE_SEC, "CTLN", b"\xff\xfe"),
            "unresolved",
            ["LABEL_FIELD_UNINTERPRETED"],
            ["U"],
            True,
        ),
        (
            "R file and image and REL",
            m(m(m(base, FILE_SEC, "CLAS", b"R"), IMAGE_SEC, "CLAS", b"R"), FILE_SEC, "REL", b"XA"),
            "labelled",
            ["CLAS_NOT_U", "RESTRICTIVE_CAVEAT"],
            ["R"],
            True,
        ),
        (
            "text CLAS C",
            m(text, text_sec, "CLAS", b"C"),
            "labelled",
            ["CLAS_NOT_U"],
            ["C", "U"],
            False,
        ),
        (
            "text CLAS blank",
            m(text, text_sec, "CLAS", b" "),
            "unresolved",
            ["CLAS_UNRECOGNISED"],
            ["", "U"],
            False,
        ),
        ("unknown TRE", tre, "unresolved", ["UNKNOWN_EXTENSION"], ["U"], True),
        (
            "unknown TRE and file CLAS R",
            m(tre, FILE_SEC, "CLAS", b"R"),
            "unresolved",
            ["UNKNOWN_EXTENSION", "CLAS_NOT_U"],
            ["R", "U"],
            False,
        ),
    ]


def test_the_assessment_truth_table_holds_on_product_footprint_and_parsed_container():
    rows = _rows()
    assert len(rows) == 20
    for name, raw, status, reasons, clas_values, uniform in rows:
        found = _assessment(raw)
        assert (found["status"], found["reasons"]) == (status, reasons), name
        assert (found["clas_values"], found["uniform_clas"]) == (clas_values, uniform), name


def test_the_unknown_duplicate_tre_assessment_record():
    assert _assessment(vector("unknown_duplicate_tre.ntf")) == {
        "status": "unresolved",
        "reasons": ["UNKNOWN_EXTENSION"],
        "scopes": 2,
        "clas_values": ["U"],
        "uniform_clas": True,
        "unknown_extensions": {"tre": 2, "des": 0, "res": 0},
        "combination": "not_performed",
        "kind": "core_assessment",
    }


def test_a_graphic_is_neutral_and_a_des_or_res_is_unresolved():
    graphic = KIT.container([KIT.image()], others=[("S", graphic_sh(2, 1), b"abc")])
    found = _assessment(graphic)
    assert (found["status"], found["scopes"]) == ("declared_unclassified", 3)
    des = KIT.container([KIT.image()], others=[("D", des_sh("SCOPAQUE"), b"abcd")])
    found = _assessment(des)
    assert (found["status"], found["reasons"]) == ("unresolved", ["UNKNOWN_EXTENSION"])
    assert found["unknown_extensions"] == {"tre": 0, "des": 1, "res": 0}
    res = KIT.container([KIT.image()], others=[("R", res_sh(), b"ab")])
    found = _assessment(res)
    assert (found["status"], found["unknown_extensions"]) == (
        "unresolved",
        {"tre": 0, "des": 0, "res": 1},
    )
    text = _assessment(vector("image_and_text.ntf"))
    assert (text["status"], text["scopes"]) == ("declared_unclassified", 3)


# --------------------------------------------------------------------------- no enforcement


def test_restricted_and_unresolved_material_still_translates_with_its_labels():
    secret = sec_patch(vector("geo_dms.ntf"), FILE_SEC, "CLAS", b"S")
    for raw, count, status in (
        (vector("unknown_duplicate_tre.ntf"), 1, "unresolved"),
        (secret, 2, "labelled"),
    ):
        objects = translate(raw)
        assert len(objects) == count
        for index in range(count):
            block = residual(objects, index)["security"]
            assert block["labels"] and block["assessment"]["status"] == status


def test_no_core_module_raises_e_policy():
    for name in ("stanag4545.py", "nsif_codec.py", "nsif_geometry.py"):
        tree = ast.parse((PACKAGE / "adapters" / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                values = list(node.args) + [k.value for k in node.keywords if k.arg == "code"]
                assert not any(
                    isinstance(v, ast.Constant) and v.value == "E_POLICY" for v in values
                ), name


def test_an_encrypted_container_is_refused_by_the_parser():
    encrypted = patch(vector("geo_dms.ntf"), 296, b"1")
    for call in (adapter().to_cdm, lambda raw: nsif_codec.parse_container(raw, LIMITS)):
        assert coded(refusal(call, encrypted)) == (
            "E_ENCRYPTED",
            "header",
            296,
            "/file_header/ENCRYP",
        )
    other = patch(vector("geo_dms.ntf"), 296, b"X")
    assert coded(refusal(adapter().to_cdm, other)) == (
        "E_FIELD",
        "header",
        296,
        "/file_header/ENCRYP",
    )


# --------------------------------------------------------------------------- the product residual


def test_the_product_residual_has_its_six_keys_and_the_octets_once():
    for stem in TOP_LEVEL:
        raw = vector(f"{stem}.ntf")
        for source in (raw, twin(stem)):
            product = adapter().to_cdm(source)[0]
            data = product.residual.data["stanag4545"]
            assert list(data) == [
                "wire_b64",
                "file_header",
                "segments",
                "extensions",
                "security",
                "parse_profile",
            ]
            assert base64.b64decode(data["wire_b64"], validate=True) == raw
            assert data["wire_b64"] == base64.b64encode(raw).decode("ascii")


def test_the_parse_profile_record():
    assert residual(translate(vector("mode_B.ntf")))["parse_profile"] == {
        "profile": "SC4545-CORE-1",
        "profile_revision": 1,
        "adapter_version": "1.0.0",
        "tre_plugins": [],
        "capabilities": {
            "container_inventory": "complete",
            "metadata_preservation": "byte_preserving",
            "cdm_translation": "complete",
            "native_samples": "per_image",
            "compressed_samples": "disabled",
            "geographic_footprint": "per_image",
            "replay": "host_operation",
            "new_export": "not_in_core",
        },
    }


def test_the_file_header_record_of_mono_nsif101():
    header = residual(translate(vector("mono_nsif101.ntf")))["file_header"]
    assert list(header) == ["offset", "length", "fields", "security", "directory"]
    assert (header["offset"], header["length"], header["security"]) == (
        0,
        404,
        {"offset": 119, "length": 167},
    )
    expected = {
        "FHDR": {"offset": 0, "length": 4, "text": "NSIF"},
        "FVER": {"offset": 4, "length": 5, "text": "01.01"},
        "CLEVEL": {"offset": 9, "length": 2, "text": "03"},
        "STYPE": {"offset": 11, "length": 4, "text": "BF01"},
        "OSTAID": {"offset": 15, "length": 10, "text": "SCFIX"},
        "FDT": {"offset": 25, "length": 14, "text": "20261004120000"},
        "FTITLE": {"offset": 39, "length": 80, "text": "SYNTHETIC ENGINEERING VECTOR"},
        "FSCOP": {"offset": 286, "length": 5, "text": "00000"},
        "FSCPYS": {"offset": 291, "length": 5, "text": "00000"},
        "ENCRYP": {"offset": 296, "length": 1, "text": "0"},
        "FBKGC": {"offset": 297, "length": 3, "values": [0, 0, 0]},
        "ONAME": {"offset": 300, "length": 24, "text": "SYNAPSECOMMAND TEST"},
        "OPHONE": {"offset": 324, "length": 18, "text": ""},
        "FL": {"offset": 342, "length": 12, "text": "000000000847"},
        "HL": {"offset": 354, "length": 6, "text": "000404"},
        "NUMI": {"offset": 360, "length": 3, "text": "001"},
        "NUMS": {"offset": 379, "length": 3, "text": "000"},
        "NUMX": {"offset": 382, "length": 3, "text": "000"},
        "NUMT": {"offset": 385, "length": 3, "text": "000"},
        "NUMDES": {"offset": 388, "length": 3, "text": "000"},
        "NUMRES": {"offset": 391, "length": 3, "text": "000"},
        "UDHDL": {"offset": 394, "length": 5, "text": "00000"},
        "XHDL": {"offset": 399, "length": 5, "text": "00000"},
    }
    assert header["fields"] == expected
    assert list(header["fields"]) == list(expected)
    assert header["directory"] == {
        "image": [
            {
                "subheader_length": {"offset": 363, "length": 6, "text": "000439"},
                "data_length": {"offset": 369, "length": 10, "text": "0000000004"},
            }
        ],
        "graphic": [],
        "text": [],
        "des": [],
        "res": [],
    }


def test_the_image_segment_entry_of_mono_nsif101():
    segment = residual(translate(vector("mono_nsif101.ntf")))["segments"][0]
    assert list(segment) == [
        "kind",
        "index",
        "ordinal",
        "subheader",
        "data",
        "security",
        "fields",
        "comments",
        "bands",
    ]
    assert (segment["kind"], segment["index"], segment["ordinal"]) == ("image", 0, 0)
    assert segment["subheader"] == {"offset": 404, "length": 439}
    assert segment["data"] == {"offset": 843, "length": 4}
    assert segment["security"] == {"offset": 527, "length": 167}
    assert segment["comments"] == []
    assert segment["bands"] == [
        {
            "fields": {
                "IREPBAND": {"offset": 780, "length": 2, "text": "M"},
                "ISUBCAT": {"offset": 782, "length": 6, "text": ""},
                "IFC": {"offset": 788, "length": 1, "text": "N"},
                "IMFLT": {"offset": 789, "length": 3, "text": ""},
                "NLUTS": {"offset": 792, "length": 1, "text": "0"},
            },
            "luts": [],
        }
    ]
    fields = segment["fields"]
    assert list(fields) == [
        "IM",
        "IID1",
        "IDATIM",
        "TGTID",
        "IID2",
        "ENCRYP",
        "ISORCE",
        "NROWS",
        "NCOLS",
        "PVTYPE",
        "IREP",
        "ICAT",
        "ABPP",
        "PJUST",
        "ICORDS",
        "NICOM",
        "IC",
        "NBANDS",
        "ISYNC",
        "IMODE",
        "NBPR",
        "NBPC",
        "NPPBH",
        "NPPBV",
        "NBPP",
        "IDLVL",
        "IALVL",
        "ILOC",
        "IMAG",
        "UDIDL",
        "IXSHDL",
    ]
    assert fields["IID1"] == {"offset": 406, "length": 10, "text": "SCFIX0001"}
    assert fields["ICORDS"] == {"offset": 775, "length": 1, "text": ""}
    assert fields["IMAG"] == {"offset": 829, "length": 4, "text": "1.0"}
    assert fields["IXSHDL"] == {"offset": 838, "length": 5, "text": "00000"}


def test_comments_luts_and_extension_bodies_are_slices_or_text_in_their_groups():
    raw = vector("vectors/native_lut3.ntf")
    segment = residual(translate(raw))["segments"][0]
    band = segment["bands"][0]
    assert band["fields"]["NLUTS"]["text"] == "3"
    assert band["fields"]["NELUTS"]["text"] == "00004"
    # Three tables of four entries each from LUTD at 798.
    assert band["luts"] == [
        {"offset": 798, "length": 4},
        {"offset": 802, "length": 4},
        {"offset": 806, "length": 4},
    ]
    hostile = _hostile()
    segment = residual(translate(hostile))["segments"][0]
    assert segment["comments"] == [
        {"offset": 777, "length": 80, "text": "http://example.invalid/x COMMENT"}
    ]
    assert "ICOM[0]" not in segment["fields"]
    tre = residual(translate(vector("unknown_duplicate_tre.ntf")))["segments"][0]["fields"]
    assert tre["IXSHDL"] == {"offset": 838, "length": 5, "text": "00031"}
    assert tre["IXSOFL"] == {"offset": 843, "length": 3, "text": "000"}
    assert tre["IXSHD"] == {"offset": 846, "length": 28}
    assert list(tre)[-3:] == ["IXSHDL", "IXSOFL", "IXSHD"]


def test_a_field_that_is_not_printable_is_written_uninterpreted():
    header = residual(translate(mono_with(FTITLE=b"\xff")))["file_header"]
    assert header["fields"]["FTITLE"] == {
        "offset": 39,
        "length": 80,
        "text": None,
        "encoding_status": "uninterpreted",
    }


def test_the_extensions_of_unknown_duplicate_tre_in_logical_order():
    assert residual(translate(vector("unknown_duplicate_tre.ntf")))["extensions"] == [
        {
            "area": "IXSHD",
            "scope": "image",
            "segment_index": 0,
            "ordinal": 0,
            "origin": "local",
            "overflow_des_index": None,
            "tag": "SCZZZZ",
            "offset": 846,
            "length": 14,
            "data": {"offset": 857, "length": 3},
        },
        {
            "area": "IXSHD",
            "scope": "image",
            "segment_index": 0,
            "ordinal": 1,
            "origin": "local",
            "overflow_des_index": None,
            "tag": "SCZZZZ",
            "offset": 860,
            "length": 14,
            "data": {"offset": 871, "length": 3},
        },
    ]


def _overflow_vector() -> bytes:
    """`mono_nsif101`'s image with one local TRE whose IXSHD names DES 1, and a TRE_OVERFLOW DES
    holding one continuation TRE. HL 417 (one DES directory entry), the image at 417 with IXSHDL at
    851 and IXSOFL at 856, the local TRE at 859, image data at 873, the DES subheader at 877 and
    its payload at 1086; 1099 octets."""
    sh, pixels = KIT.image(tre=b"SCZZZZ00003abc")
    sh = sh[: -14 - 3] + b"001" + sh[-14:]
    overflow = des_sh("TRE_OVERFLOW", ("IXSHD", 1))
    return KIT.container([(sh, pixels)], others=[("D", overflow, b"SCYYYY00002xy")])


def test_overflow_records_follow_the_local_ones_with_their_des():
    raw = _overflow_vector()
    assert len(raw) == 1099
    data = residual(translate(raw))
    assert data["extensions"] == [
        {
            "area": "IXSHD",
            "scope": "image",
            "segment_index": 0,
            "ordinal": 0,
            "origin": "local",
            "overflow_des_index": None,
            "tag": "SCZZZZ",
            "offset": 859,
            "length": 14,
            "data": {"offset": 870, "length": 3},
        },
        {
            "area": "IXSHD",
            "scope": "image",
            "segment_index": 0,
            "ordinal": 1,
            "origin": "overflow",
            "overflow_des_index": 0,
            "tag": "SCYYYY",
            "offset": 1086,
            "length": 13,
            "data": {"offset": 1097, "length": 2},
        },
    ]
    des = data["segments"][1]
    assert (des["kind"], des["index"], des["ordinal"]) == ("des", 0, 1)
    assert des["subheader"] == {"offset": 877, "length": 209}
    assert des["data"] == {"offset": 1086, "length": 13}
    assert des["fields"] == {
        "DE": {"offset": 877, "length": 2, "text": "DE"},
        "DESID": {"offset": 879, "length": 25, "text": "TRE_OVERFLOW"},
        "DESVER": {"offset": 904, "length": 2, "text": "01"},
        "DESOFLW": {"offset": 1073, "length": 6, "text": "IXSHD"},
        "DESITEM": {"offset": 1079, "length": 3, "text": "001"},
        "DESSHL": {"offset": 1082, "length": 4, "text": "0000"},
        "DESSHF": {"offset": 1086, "length": 0},
    }
    image = data["segments"][0]["fields"]
    assert image["IXSOFL"] == {"offset": 856, "length": 3, "text": "001"}
    assert image["IXSHD"] == {"offset": 859, "length": 14}
    assert data["security"]["assessment"]["unknown_extensions"] == {"tre": 2, "des": 1, "res": 0}


def _slices(node):
    if isinstance(node, dict):
        if set(node) >= {"offset", "length"} and isinstance(node.get("length"), int):
            if node.get("offset") is not None:
                yield node["offset"], node["length"]
        for value in node.values():
            yield from _slices(value)
    elif isinstance(node, list):
        for value in node:
            yield from _slices(value)


def test_every_slice_lies_inside_the_input():
    for raw in [vector(f"{stem}.ntf") for stem in TOP_LEVEL] + [_overflow_vector()]:
        for offset, length in _slices(translate(raw)):
            assert 0 <= offset <= offset + length <= len(raw)


def test_no_residual_key_reads_as_a_time_or_an_identity():
    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    for stem in TOP_LEVEL:
        for item in translate(vector(f"{stem}.ntf")):
            for key in keys(item["residual"]):
                assert not key.endswith(("_at", "_from", "_to")), key
                assert key not in ("entity_id", "event_id", "track_id", "object_id"), key


# --------------------------------------------------------------------------- the footprint


def test_the_geo_dms_footprint_plan_object():
    footprint = translate(vector("geo_dms.ntf"))[1]
    assert footprint["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[17.0, 48.0], [17.0, 47.0], [18.0, 47.0], [18.0, 48.0], [17.0, 48.0]]],
    }
    assert footprint["object_type"] == "ANNOTATION"
    assert footprint["label"] == "SCFIX0001"
    assert footprint["style"] == {}
    for name in ("expires_at", "route", "area", "quality", "status", "integrity"):
        assert footprint[name] is None, name


def test_a_blank_iid1_labels_the_footprint_by_its_ordinal():
    objects = translate(
        geo_with(IID1=b" " * 10), context=Stanag4545Context(product_key="EXERCISE-CASES-0001")
    )
    assert objects[1]["label"] == "Image 1"
    assert residual(objects, 1)["label_basis"] == "image_ordinal"
    assert objects[1]["source"]["transformations"][0] == T["UTC reformatting"]


def test_an_invalid_corner_gives_no_footprint():
    objects = translate(geo_with(IGEOLO=b"486000N" + GEO[7:].encode()))
    assert len(objects) == 1
    record = objects[0]["attributes"]["stanag4545"]
    assert record["images"][0]["geometry_status"] == "invalid"
    assert [d["code"] for d in record["diagnostics"]] == ["GEOMETRY_INVALID"]


def test_only_the_image_with_corners_gets_a_footprint():
    raw = KIT.container([KIT.image(), KIT.image(geo=GEO)])
    objects = translate(raw)
    assert [(o["object_kind"], o["source"]["record_index"]) for o in objects] == [
        ("entity", 0),
        ("plan_object", 1),
    ]
    assert objects[1]["label"] == "SCFIX0001"
    data = residual(objects)
    entry = next(s for s in data["segments"] if s["kind"] == "image" and s["index"] == 1)
    assert residual(objects, 1)["image"] == entry
    assert data["segments"].index(entry) == 1
    assert [
        image["geometry_status"] for image in objects[0]["attributes"]["stanag4545"]["images"]
    ] == [
        "absent",
        "available",
    ]


def test_the_geo_dms_footprint_residual():
    objects = translate(vector("geo_dms.ntf"))
    data = residual(objects, 1)
    assert list(data) == [
        "presentation",
        "product",
        "image",
        "footprint",
        "label_basis",
        "security",
        "diagnostics",
    ]
    assert data["presentation"] == {"role": "coverage_overlay", "type_label": "imagery footprint"}
    assert data["product"] == {
        "product_entity_id": ENTITY_NSIF101,
        "system": "STANAG4545:default",
        "product_key": KEY,
        "profile": "SC4545-CORE-1",
        "wire_signature": "NSIF01.01",
        "image_count": 1,
    }
    assert data["product"]["product_entity_id"] == objects[0]["entity_id"]
    assert data["image"] == residual(objects)["segments"][0]
    assert data["footprint"] == {
        "geometry_basis": "IGEOLO",
        "precision": "source_corner_encoding",
        "accuracy_m": None,
        "orthorectified": False,
        "icords": "G",
        "igeolo": {"offset": 776, "length": 60, "text": GEO},
        "corners": [[17.0, 48.0], [18.0, 48.0], [18.0, 47.0], [17.0, 47.0]],
        "reversed": True,
        "split": False,
        "seam_corner": False,
        "duplicates_removed": False,
    }
    assert data["label_basis"] == "IID1"
    product_security = residual(objects)["security"]
    assert data["security"] == {
        "label_scope": [{"scope": "file", "index": None}, {"scope": "image", "index": 0}],
        "labels": product_security["labels"],
        "assessment": product_security["assessment"],
    }
    assert data["diagnostics"] == []
    assert "wire_b64" not in json.dumps(data)


def test_a_gate_reading_only_the_footprint_decides_as_on_the_product():
    objects = translate(sec_patch(vector("geo_dms.ntf"), IMAGE_SEC, "CLAS", b"R"))
    status = residual(objects, 1)["security"]["assessment"]["status"]
    assert status == "labelled" == objects[0]["attributes"]["stanag4545"]["security_status"]


def test_the_footprint_carries_its_own_image_s_diagnostics_only():
    raw = geo_with(IID2=b"\xff", FTITLE=b"\xfe")
    objects = translate(raw)
    product = [
        (d["code"], d["path"]) for d in objects[0]["attributes"]["stanag4545"]["diagnostics"]
    ]
    assert product == [
        ("TEXT_UNINTERPRETED", "/file_header/FTITLE"),
        ("TEXT_UNINTERPRETED", "/segments/image[0]/IID2"),
    ]
    assert residual(objects, 1)["diagnostics"] == [
        {
            "code": "TEXT_UNINTERPRETED",
            "stage": "segment",
            "offset": 447,
            "path": "/segments/image[0]/IID2",
            "message": "descriptive text holds octets outside printable ASCII and is not interpreted",
        }
    ]


# --------------------------------------------------------------------------- provenance


def test_the_source_refs_of_geo_dms():
    objects = translate(vector("geo_dms.ntf"))
    product, footprint = objects[0]["source"], objects[1]["source"]
    assert product == {
        "system": "STANAG4545",
        "adapter": "stanag4545",
        "adapter_version": "1.0.0",
        "synthetic": True,
        "format_name": "NSIF/NITF imagery",
        "format_version": "SC4545-CORE-1; STANAG 4545 Ed 2 target",
        "original_id": KEY,
        "source_hash": None,
        "record_index": 0,
        "observed_at": None,
        "transformations": [
            T["ASCII display trimming"],
            T["UTC reformatting"],
            T["integer conversion"],
        ],
    }
    assert footprint["record_index"] == 0
    assert footprint["original_id"] == KEY
    assert footprint["transformations"] == [
        T["ASCII display trimming"],
        T["UTC reformatting"],
        T["IGEOLO corner coordinates"],
        T["IGEOLO ring orientation"],
    ]


def test_the_host_digest_reaches_every_source_hash_and_integrity_stays_null():
    raw = vector("geo_dms.ntf")
    digest = hashlib.sha256(raw).hexdigest()
    objects = translate(raw, context=Stanag4545Context(verified_sha256=digest))
    for item in objects:
        assert item["source"]["source_hash"] == {"algorithm": "sha256", "value": digest}
        assert item["integrity"] is None
    for item in translate(raw):
        assert item["source"]["source_hash"] is None


# --------------------------------------------------------------------------- TRANSFORMS, MAPPINGS


def test_transforms_declares_the_seven_reasons():
    assert list(T) == [
        "ASCII display trimming",
        "UTC reformatting",
        "date fallback",
        "integer conversion",
        "IGEOLO corner coordinates",
        "IGEOLO ring orientation",
        "IGEOLO antimeridian splitting",
    ]
    assert all(value.isascii() for value in T.values())
    assert not any(
        k == p or k.startswith(p + ".") or k.startswith(p + "[")
        for k in T
        for p in ("profile", "wire_b64")
    )
    assert T["IGEOLO corner coordinates"] is nsif_geometry.REASON_COORDINATES
    assert T["IGEOLO ring orientation"] is nsif_geometry.REASON_ORIENTATION
    assert T["IGEOLO antimeridian splitting"] is nsif_geometry.REASON_SPLITTING
    assert T["date fallback"] == (
        "valid_from is the caller's context.as_of instant because FDT is unknown or not "
        "representable; the clock, the epoch and IDATIM are never substituted"
    )


def test_every_recorded_transformation_is_a_declared_reason():
    declared = set(T.values())
    fallback = T["date fallback"] + " Basis: "
    as_of = AsOf("2026-01-02T03:04:05Z", "exercise context instant")
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001", as_of=as_of)
    outputs = [translate(vector(f"{stem}.ntf")) for stem in TOP_LEVEL]
    outputs.append(translate(geo_with(FDT=b" " * 14), context=context))
    for objects in outputs:
        for item in objects:
            for line in item["source"]["transformations"]:
                assert line in declared or line.startswith(fallback), line


def test_the_ledger_binds_both_twin_leaves():
    assert Stanag4545Adapter.MAPPINGS == {
        "profile": lossless.Mapping("entity:attributes.stanag4545.profile"),
        "wire_b64": lossless.Mapping("entity:residual.data.stanag4545.wire_b64"),
    }
    expected = {"MAPPED": 2, "RESIDUAL": 0, "DECLARED_LIMITATION": 0, "LOST": 0}
    only_wire = {"wire_b64": Stanag4545Adapter.MAPPINGS["wire_b64"]}
    for stem in TOP_LEVEL:
        document = twin(stem)
        dumped = translate(document)
        assert lossless.ledger(document, dumped, Stanag4545Adapter.MAPPINGS).counts == expected
        assert lossless.ledger(document, dumped, only_wire).counts["LOST"] == 1


def test_retention_and_interpretation_are_asserted_independently():
    # The ledger proves the octets are kept whatever a field says, so a changed field leaves it
    # whole; what the field is read as is asserted separately, against hand-written literals.
    document = _twin_of(patch(vector("mono_nsif101.ntf"), 430, b"EXERCISE TGT 01  "))
    dumped = translate(document)
    assert lossless.ledger(document, dumped, Stanag4545Adapter.MAPPINGS).counts == {
        "MAPPED": 2,
        "RESIDUAL": 0,
        "DECLARED_LIMITATION": 0,
        "LOST": 0,
    }
    assert residual(dumped)["segments"][0]["fields"]["TGTID"] == {
        "offset": 430,
        "length": 17,
        "text": "EXERCISE TGT 01",
    }
    image = translate(vector("uint16.ntf"))[0]["attributes"]["stanag4545"]["images"][0]
    assert (image["abpp"], image["nbpp"], image["rows"], image["columns"]) == (16, 16, 2, 2)


# --------------------------------------------------------------------------- output caps


def test_the_object_bound_admits_sixty_five_and_refuses_one_more_by_injection(monkeypatch):
    raw = KIT.container([KIT.image(geo=GEO) for _ in range(64)])
    assert len(raw) == 33_604
    objects = adapter().to_cdm(raw)
    assert len(objects) == 65
    assert [o.source.record_index for o in objects[1:]] == list(range(64))
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_objects=64))
    error = refusal(adapter().to_cdm, raw)
    assert coded(error) == ("E_LIMIT", "cdm", None, "/cdm/objects")
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_objects=65))
    assert len(adapter().to_cdm(raw)) == 65
    # A 65th image is refused by the image-segment cap before any object is counted.
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", LIMITS)
    over = KIT.container([KIT.image(geo=GEO) for _ in range(65)])
    assert coded(refusal(adapter().to_cdm, over)) == ("E_LIMIT", "header", 360, "/file_header/NUMI")


def test_two_footprints_under_an_object_cap_of_two_are_refused(monkeypatch):
    raw = KIT.container([KIT.image(geo=GEO), KIT.image(geo=GEO)])
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_objects=2))
    assert coded(refusal(adapter().to_cdm, raw)) == ("E_LIMIT", "cdm", None, "/cdm/objects")
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_objects=3))
    assert len(adapter().to_cdm(raw)) == 3


def test_the_serialised_output_bound_admits_its_size_and_refuses_one_less(monkeypatch):
    raw = vector("geo_dms.ntf")
    objects = adapter().to_cdm(raw)
    size = len(
        json.dumps(
            [item.model_dump(mode="json") for item in objects],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_bytes=size))
    assert len(adapter().to_cdm(raw)) == 2
    monkeypatch.setattr(nsif_codec, "CORE1_LIMITS", Limits(output_bytes=size - 1))
    assert coded(refusal(adapter().to_cdm, raw)) == ("E_LIMIT", "cdm", None, "/cdm/serialized")


def test_the_output_caps_the_wire_cannot_reach_by_arithmetic():
    assert 9 * 99_999 < Limits().lut_bytes
    assert 1 + Limits().images == Limits().output_objects == 65
    assert Limits().output_bytes == 67_108_864


# --------------------------------------------------------------------------- the manifest


def test_the_manifest_declaration():
    meta = Stanag4545Adapter.metadata
    assert meta.id == "stanag4545" and meta.name == "STANAG 4545 NSIF/NITF imagery"
    assert meta.adapter_version == "1.0.0"
    assert (meta.format.name, meta.format.version) == (
        "NSIF/NITF imagery",
        "SC4545-CORE-1; STANAG 4545 Ed 2 target",
    )
    assert meta.binding is WireBinding.PROVISIONAL_INTERNAL_PROFILE
    assert meta.claim_status is ClaimStatus.PROVISIONAL
    assert meta.claim_external_system is None
    assert meta.maturity.level is MaturityLevel.L3
    assert meta.maturity.external_exercise is None
    assert meta.evidence.available is False
    assert meta.profiles == ["SC4545-CORE-1"]
    assert meta.residual is Residual.STRUCTURED
    assert meta.direction.value == "ingest"
    assert meta.license_class.value == "PUBLIC_GOVERNMENT"
    assert meta.payload_adapter is None and meta.constituents == []
    assert len(meta.limitations) == 9 and meta.limitations_empty_reason is None
    texts = [limitation_text(line) for line in meta.limitations]
    assert sum("provisional" in text.lower() for text in texts) == 1
    availability = re.compile(r"`evidence\.available` is (true|false)\b")
    assert [m.group(1) for text in texts for m in availability.finditer(text)] == ["false"]
    assert not any(re.search(r"NATO [A-Z]", text) for text in texts)
    assert texts[2] == (
        "`validate_source` checks the SC4545-CORE-1 engineering profile's structure, local "
        "semantics and resource caps; an empty list is not full STANAG 4545 validation"
    )
    document = manifests.manifest(Stanag4545Adapter)
    assert document.adapter.id == "stanag4545"


def test_the_contract_numbers_are_not_moved():
    assert Stanag4545Adapter.metadata.adapter_version == "1.0.0"
    assert version.SCHEMA_VERSION == "3.2.0"
    assert version.ADAPTER_API_VERSION == "3.1.0"


def test_the_capabilities_and_the_limit_bases():
    caps = Stanag4545Adapter.metadata.capabilities
    assert caps.wire is True and caps.directions_exercised == ["ingest"]
    assert caps.unknown_fields is UnknownFields.NONE
    assert len(caps.message_types) == 2
    assert caps.message_types[1] == (
        'the parsed twin `{"profile": "SC4545-CORE-1", "wire_b64": …}` — the same '
        "objects through the same parser"
    )
    limits = caps.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (16_777_216, 4, 65)
    assert limits.max_decompressed_bytes is None and limits.max_parse_seconds is None
    assert set(limits.declared_because) == {"max_input_bytes", "max_depth", "max_objects"}
    assert set(limits.absent_because) == {"max_decompressed_bytes", "max_parse_seconds"}
    own = pathlib.Path(__file__).read_text()
    for name, basis in limits.declared_because.items():
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP
        assert "IMPLEMENTATION CAP" in basis.source
        assert "is NOT the format's normative maximum" in basis.source
        assert len(basis.source) > 80
        path, function = basis.test.split("::")
        if name == "max_input_bytes":
            assert basis.test == (
                "tests/test_cdm_input_bounds.py::"
                "test_every_adapter_refuses_one_octet_over_its_declared_bound"
            )
            assert "class-definition" in basis.enforced_at
        else:
            assert path == "tests/test_cdm_stanag4545_adapter.py"
            assert f"def {function}(" in own
    assert limits.declared_because["max_depth"].test.endswith(
        "test_the_twin_depth_bound_admits_depth_four_shapes_and_refuses_five"
    )
    assert limits.declared_because["max_objects"].test.endswith(
        "test_the_object_bound_admits_sixty_five_and_refuses_one_more_by_injection"
    )


# --------------------------------------------------------------------------- the fixture tree


def test_the_harness_selects_the_twenty_two_top_level_fixtures():
    names = sorted(p.name for p in harness.select_fixtures(FIXTURES))
    assert names == sorted(
        [f"{stem}.ntf" for stem in TOP_LEVEL] + [f"{stem}.parsed.json" for stem in TOP_LEVEL]
    )
    assert len(names) == 22
    assert sorted(p.name for p in harness.select_fixtures(FIXTURES / "malformed")) == list(
        MALFORMED
    )
    assert sorted(p.name for p in harness.select_fixtures(FIXTURES / "context")) == [
        "header_only.ntf",
        "header_only.parsed.json",
    ]
    assert sorted(p.name for p in (FIXTURES / "golden").iterdir()) == sorted(
        [f"{stem}.cdm.json" for stem in TOP_LEVEL]
        + [f"{stem}.parsed.cdm.json" for stem in TOP_LEVEL]
    )
    assert sorted(p.name for p in (FIXTURES / "context" / "golden").iterdir()) == [
        "header_only.cdm.json",
        "header_only.parsed.cdm.json",
    ]
    assert sorted(p.name for p in (FIXTURES / "spec").iterdir() if p.name != "__pycache__") == [
        "build_fixtures.py"
    ]


def test_every_kit_named_vector_is_byte_identical_to_the_kit():
    found = {}
    for path in FIXTURES.rglob("*.ntf"):
        if path.name in KIT_VECTOR_SHA256:
            found[path.relative_to(FIXTURES).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    assert len(found) == 17
    for where, digest in found.items():
        assert digest == KIT_VECTOR_SHA256[pathlib.PurePosixPath(where).name], where


def test_the_loader_returns_the_octets_of_a_ntf_file():
    raw = harness.load_raw(FIXTURES / "mono_nsif101.ntf")
    assert type(raw) is bytes and raw == vector("mono_nsif101.ntf")


def test_the_harness_replays_the_shipped_class_over_an_explicit_directory(capsys):
    assert harness.main(["--adapter", "stanag4545", "--fixtures", str(FIXTURES)]) == 0
    assert "22 passed, 0 failed" in capsys.readouterr().out


def test_every_malformed_payload_is_refused_by_the_adapter():
    for name in MALFORMED:
        assert coded(refusal(adapter().to_cdm, vector(f"malformed/{name}")))[0].startswith("E_")


def test_each_twin_is_the_canonical_envelope_of_its_vector():
    stems = [(stem, FIXTURES) for stem in TOP_LEVEL] + [("header_only", FIXTURES / "context")]
    for stem, directory in stems:
        text = (directory / f"{stem}.parsed.json").read_text()
        octets = (directory / f"{stem}.ntf").read_bytes()
        expected = {
            "profile": "SC4545-CORE-1",
            "wire_b64": base64.b64encode(octets).decode("ascii"),
        }
        assert json.loads(text) == expected
        assert text == json.dumps(expected, indent=2) + "\n"


def test_each_twin_golden_is_its_container_golden_and_translates_identically():
    for stem in TOP_LEVEL:
        golden = FIXTURES / "golden"
        assert (golden / f"{stem}.cdm.json").read_bytes() == (
            golden / f"{stem}.parsed.cdm.json"
        ).read_bytes()
        assert translate(vector(f"{stem}.ntf")) == translate(twin(stem))
    context = FIXTURES / "context" / "golden"
    assert (context / "header_only.cdm.json").read_bytes() == (
        context / "header_only.parsed.cdm.json"
    ).read_bytes()


def test_no_packaged_json_nests_past_sixteen_or_spells_the_retired_name():
    retired = "nf" + "fi"
    for path in FIXTURES.rglob("*.json"):
        text = path.read_text()
        assert adapter_module.json_nesting_depth(text) <= 16, path
        assert retired not in text.lower(), path


def test_the_provenance_records_and_twins_are_complete():
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES / "context") == []
    for directory in (FIXTURES, FIXTURES / "malformed", FIXTURES / "context"):
        record = json.loads((directory / "PROVENANCE.json").read_text())
        listed = [entry["file"] for entry in record["fixtures"]]
        assert listed == [p.name for p in harness.select_fixtures(directory)]
        assert all(entry["synthetic"] is True for entry in record["fixtures"])


def test_product_keys_in_the_packaged_tree_and_this_module_are_slugs():
    pattern = re.compile(r'product_key"?\s*[:=]\s*"((?:[^"\\]|\\.)*)"')
    slug = re.compile(r"^(EXERCISE-[A-Z0-9-]+-[0-9]{4}|\[.*\])$")
    seen = 0
    for path in FIXTURES.rglob("*"):
        if path.suffix in (".json", ".md", ".py"):
            for value in pattern.findall(path.read_text()):
                seen += 1
                assert slug.match(value), (path, value)
    assert seen > 0
    for value in pattern.findall(pathlib.Path(__file__).read_text()):
        assert value == "" or len(value) < 20 or value.startswith("EXERCISE-"), value


# --------------------------------------------------------------------------- the builder


def test_the_builder_owns_exactly_the_packaged_payloads_and_reproduces_them():
    built = _build_fixtures_module().fixtures()
    tracked = {
        p.relative_to(FIXTURES).as_posix()
        for p in FIXTURES.rglob("*")
        if p.is_file()
        and p.name not in ("README.md", "PROVENANCE.json")
        and p.relative_to(FIXTURES).parts[0] not in ("golden", "independent", "spec")
        and "golden" not in p.relative_to(FIXTURES).parts
        and "__pycache__" not in p.parts
    }
    assert set(built) == tracked
    assert len(built) == 76
    assert len([name for name in built if name.startswith("vectors/")]) == 47
    for name, octets in built.items():
        assert (FIXTURES / name).read_bytes() == octets, name


def test_the_builder_imports_only_the_standard_set():
    tree = ast.parse((FIXTURES / "spec" / "build_fixtures.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "argparse", "base64", "json", "pathlib", "struct", "sys"}


def test_the_builder_check_mode_reads_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


# --------------------------------------------------------------------------- the golden wrapper


def test_the_exercise_wrapper_is_unregistered_and_overrides_the_hook():
    assert "ExerciseContextAdapter" not in {c.__name__ for c in adapter_module.REGISTRY.values()}
    assert adapter_module.REGISTRY["stanag4545"] is Stanag4545Adapter
    assert harness.overrides_fixture_instance(ExerciseContextAdapter) is True
    reference = f"{__name__}:ExerciseContextAdapter"
    assert harness.fixtures_refused_message(reference, ExerciseContextAdapter) is None
    assert ExerciseContextAdapter().context == Stanag4545Context()


def test_the_context_goldens_replay_through_the_wrapper(capsys):
    reference = f"{__name__}:ExerciseContextAdapter"
    assert harness.main(["--adapter", reference, "--fixtures", str(FIXTURES / "context")]) == 0
    assert "2 passed, 0 failed" in capsys.readouterr().out
    assert harness.main(["--adapter", reference]) == 2


def test_the_wrapper_translates_header_only():
    raw = vector("context/header_only.ntf")
    objects = dump(ExerciseContextAdapter.fixture_instance(clock=times.frozen_clock()).to_cdm(raw))
    assert len(objects) == 1
    record = objects[0]["attributes"]["stanag4545"]
    assert record["product_key"] == "EXERCISE-HEADER-ONLY-0001"
    assert record["asset_ref"] == "exercise-asset-0001"
    assert record["images"] == []
    assert objects[0]["source_ids"][0]["system"] == "STANAG4545:exercise"
    assert objects[0]["source"]["source_hash"] == {
        "algorithm": "sha256",
        "value": hashlib.sha256(raw).hexdigest(),
    }
    assert objects[0]["valid_from"] == STAMP
    assert residual(objects)["security"]["assessment"]["status"] == "declared_unclassified"


def test_the_shipped_class_keeps_the_default_hook(capsys):
    assert harness.overrides_fixture_instance(Stanag4545Adapter) is False
    assert harness.fixtures_refused_message("stanag4545", Stanag4545Adapter) is None


# --------------------------------------------------------------------------- restraint


def _hostile() -> bytes:
    """`mono_nsif101` whose TGTID says HOSTILE and whose ISORCE, IID2, FTITLE and one ICOM begin
    with a URL. The comment is inserted after NICOM (image offset 372), so the image subheader
    grows by 80 octets; the comment lands at 777."""
    sh, pixels = KIT.image()
    sh = sh[:26] + KIT.a("HOSTILE", 17) + KIT.a("http://example.invalid/x IID2", 80) + sh[123:]
    sh = sh[:291] + KIT.a("http://example.invalid/x ISORCE", 42) + sh[333:]
    sh = sh[:372] + b"1" + KIT.a("http://example.invalid/x COMMENT", 80) + sh[373:]
    raw = KIT.container([(sh, pixels)])
    return patch(raw, 39, KIT.a("http://example.invalid/x TITLE", 80))


_HOSTILE_AUDIT = """
import sys
from synapse_cdm import times
from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter
raw = open(sys.argv[1], "rb").read()
instance = Stanag4545Adapter(clock=times.frozen_clock())
instance.to_cdm(raw)
events = []
def hook(event, args):
    if event.startswith(("socket.", "urllib.", "subprocess.")) or event == "open":
        events.append(event)
sys.addaudithook(hook)
objects = instance.to_cdm(raw)
print(len(objects), events)
"""


def test_nothing_is_inferred_or_dereferenced_from_hostile_descriptive_fields(tmp_path):
    raw = _hostile()
    for source in [vector(f"{stem}.ntf") for stem in TOP_LEVEL] + [raw]:
        objects = translate(source)
        assert [o["object_kind"] for o in objects] in (["entity"], ["entity", "plan_object"])
        assert objects[0]["affiliation"] == "UNKNOWN"
        values = json.dumps(objects[0]["attributes"])
        assert '"HOSTILE"' not in values and '"http' not in values
    fields = residual(translate(raw))["segments"][0]["fields"]
    assert fields["TGTID"]["text"] == "HOSTILE"
    path = tmp_path / "hostile.ntf"
    path.write_bytes(raw)
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _HOSTILE_AUDIT, str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1 []"


def test_only_the_three_core_files_exist_and_none_parses_json_or_catches_everything():
    adapters = PACKAGE / "adapters"
    for name in ("stanag4545.py", "nsif_codec.py", "nsif_geometry.py"):
        text = (adapters / name).read_text()
        for needle in (
            "json." + "loads",
            "ET." + "fromstring",
            "zip" + "file",
            "sqlite" + "3",
            "gz" + "ip",
            "zl" + "ib",
        ):
            assert needle not in text, (name, needle)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                assert node.type is not None, name
                caught = ast.unparse(node.type)
                assert caught not in ("Exception", "BaseException"), name
    subclasses = [
        p.name
        for p in adapters.glob("*.py")
        if "stanag4545" in p.read_text()
        and "class " in p.read_text()
        and "(Adapter)" in p.read_text()
    ]
    assert subclasses == ["stanag4545.py"]


# --------------------------------------------------------------------------- the host's predicate


def test_the_host_can_assess_before_translation_and_gets_the_same_record():
    for stem in TOP_LEVEL:
        raw = vector(f"{stem}.ntf")
        container = nsif_codec.parse_container(raw, LIMITS)
        objects = translate(raw)
        assert assess_security(container) == residual(objects)["security"]["assessment"]
        assert security_labels(container) == residual(objects)["security"]["labels"]
    header = nsif_codec.parse_container(vector("context/header_only.ntf"), LIMITS)
    assert assess_security(header)["status"] == "declared_unclassified"
    wrapped = dump(
        ExerciseContextAdapter.fixture_instance().to_cdm(vector("context/header_only.ntf"))
    )
    assert assess_security(header) == residual(wrapped)["security"]["assessment"]
    for function in (assess_security, security_labels):
        assert list(inspect.signature(function).parameters) == ["container"]


def test_the_labels_of_geo_dms_as_the_host_reads_them():
    labels = security_labels(nsif_codec.parse_container(vector("geo_dms.ntf"), LIMITS))
    assert labels == [
        {
            "scope": "file",
            "index": None,
            "offset": 119,
            "length": 167,
            "fields": BLANK_LABEL_FIELDS,
            "uninterpreted": [],
        },
        {
            "scope": "image",
            "index": 0,
            "offset": 527,
            "length": 167,
            "fields": BLANK_LABEL_FIELDS,
            "uninterpreted": [],
        },
    ]


def test_no_other_core_module_spells_the_assessment_reasons():
    reasons = (
        "CLAS_UNRECOGNISED",
        "LABEL_FIELD_UNINTERPRETED",
        "UNKNOWN_EXTENSION",
        "CLAS_NOT_U",
        "RESTRICTIVE_CAVEAT",
        "MIXED_CLASSIFICATION_SYSTEM",
    )
    spelled = sorted(
        p.relative_to(PACKAGE).as_posix()
        for p in PACKAGE.rglob("*.py")
        if any(reason in p.read_text() for reason in reasons)
    )
    assert spelled == ["adapters/stanag4545.py"]


def test_the_assessment_does_not_mutate_or_depend_on_a_context():
    container = nsif_codec.parse_container(vector("geo_dms.ntf"), LIMITS)
    snapshot = copy.deepcopy(security_labels(container))
    assert assess_security(container) == assess_security(container)
    assert security_labels(container) == snapshot


# --------------------------------------------------------------------------- every kit vector, by hand


def test_the_five_entry_points_have_the_specified_signatures():
    for name in ("detect", "validate_source", "to_cdm"):
        assert list(inspect.signature(getattr(Stanag4545Adapter, name)).parameters) == [
            "self",
            "raw",
        ], name
    assert list(inspect.signature(nsif_codec.parse_container).parameters) == ["raw", "limits"]
    window = inspect.signature(nsif_codec.decode_nc_window).parameters
    assert list(window) == [
        "container",
        "image_index",
        "x",
        "y",
        "width",
        "height",
        "bands",
        "storage",
    ]
    assert window["storage"].kind is inspect.Parameter.KEYWORD_ONLY
    assert window["storage"].default is False


def _image_record(rows=2, columns=2, bands=1, abpp=8, nbpp=8, mode="B", geometry="absent"):
    return {
        "index": 0,
        "iid1": "SCFIX0001",
        "capture_time": STAMP,
        "rows": rows,
        "columns": columns,
        "bands": bands,
        "pvtype": "INT",
        "abpp": abpp,
        "nbpp": nbpp,
        "compression": "NC",
        "mode": mode,
        "pixel_status": "native_supported",
        "geometry_status": geometry,
        "composition_status": "segment_only",
    }


#: Per kit vector, from the kit generator's parameters: the signature, the one image record, the
#: product identity, the security status, and the offsets of its security blocks (the file's at
#: 119; the image's 123 octets into a subheader at HL, which is 404 with one directory entry and
#: 413 with the image and text entries; the text's 106 octets into its subheader at 856).
KIT_RECORDS = {
    "mono_nsif101": (
        "NSIF01.01",
        _image_record(),
        ENTITY_NSIF101,
        "declared_unclassified",
        [119, 527],
    ),
    "mono_nsif100": (
        "NSIF01.00",
        _image_record(),
        ENTITY_NSIF100,
        "declared_unclassified",
        [119, 527],
    ),
    "mono_nitf210": (
        "NITF02.10",
        _image_record(),
        ENTITY_NITF210,
        "declared_unclassified",
        [119, 527],
    ),
    "geo_dms": (
        "NSIF01.01",
        _image_record(geometry="available"),
        ENTITY_NSIF101,
        "declared_unclassified",
        [119, 527],
    ),
    "unknown_duplicate_tre": (
        "NSIF01.01",
        _image_record(),
        ENTITY_NSIF101,
        "unresolved",
        [119, 527],
    ),
    "uint16": (
        "NSIF01.01",
        _image_record(abpp=16, nbpp=16),
        ENTITY_NSIF101,
        "declared_unclassified",
        [119, 527],
    ),
    "image_and_text": (
        "NSIF01.01",
        _image_record(),
        ENTITY_NSIF101,
        "declared_unclassified",
        [119, 536, 962],
    ),
    **{
        f"mode_{mode}": (
            "NSIF01.01",
            _image_record(rows=4, columns=4, bands=3, mode=mode),
            ENTITY_NSIF101,
            "declared_unclassified",
            [119, 527],
        )
        for mode in "BPRS"
    },
}


@pytest.mark.parametrize("stem", TOP_LEVEL)
def test_every_kit_vector_translates_to_its_hand_written_record(stem):
    signature, image, entity, status, blocks = KIT_RECORDS[stem]
    objects = translate(vector(f"{stem}.ntf"))
    record = objects[0]["attributes"]["stanag4545"]
    assert record["wire_signature"] == signature
    assert record["images"] == [image]
    assert record["security_status"] == status
    assert record["diagnostics"] == []
    assert objects[0]["entity_id"] == entity
    labels = residual(objects)["security"]["labels"]
    assert [label["offset"] for label in labels] == blocks
    assert [(label["scope"], label["index"]) for label in labels] == [("file", None)] + [
        (scope, 0) for scope in ("image", "text")[: len(blocks) - 1]
    ]
    for label in labels:
        assert label["fields"] == BLANK_LABEL_FIELDS and label["uninterpreted"] == []
    # The text segment's payload is preserved as a slice and never read as text.
    assert "<script" not in json.dumps(objects)


def test_a_footprint_across_the_antimeridian_is_a_two_part_multipolygon():
    seam = "480000N1790000E480000N1790000W470000N1790000W470000N1790000E"
    objects = translate(KIT.container([KIT.image(geo=seam)]))
    footprint = objects[1]
    # The stated ring winds clockwise, so it is reversed with the upper-left corner first, then
    # clipped at 180 by one Sutherland-Hodgman pass, the west part first, the east part shifted.
    assert footprint["geometry"] == {
        "type": "MultiPolygon",
        "coordinates": [
            [[[180.0, 48.0], [179.0, 48.0], [179.0, 47.0], [180.0, 47.0], [180.0, 48.0]]],
            [[[-180.0, 48.0], [-180.0, 47.0], [-179.0, 47.0], [-179.0, 48.0], [-180.0, 48.0]]],
        ],
    }
    assert footprint["source"]["transformations"] == [
        T["ASCII display trimming"],
        T["UTC reformatting"],
        T["IGEOLO corner coordinates"],
        T["IGEOLO ring orientation"],
        T["IGEOLO antimeridian splitting"],
    ]
    record = residual(objects, 1)["footprint"]
    assert (record["reversed"], record["split"], record["seam_corner"]) == (True, True, False)
    assert record["corners"] == [[179.0, 48.0], [-179.0, 48.0], [-179.0, 47.0], [179.0, 47.0]]


def test_d_corners_reach_the_plan_object():
    objects = translate(vector("vectors/native_geo_d_northup.ntf"))
    assert objects[1]["geometry"] == {
        "type": "Polygon",
        "coordinates": [
            [[20.5, 58.25], [20.5, 56.75], [24.25, 56.75], [24.25, 58.25], [20.5, 58.25]]
        ],
    }
    data = residual(objects, 1)["footprint"]
    assert data["icords"] == "D"
    assert data["igeolo"] == {
        "offset": 776,
        "length": 60,
        "text": "+58.250+020.500+58.250+024.250+56.750+024.250+56.750+020.500",
    }
    south_up = translate(vector("vectors/native_geo_g_southup.ntf"))[1]
    assert south_up["geometry"]["coordinates"] == [
        [[21.0, 57.0], [23.5, 57.0], [23.5, 58.0], [21.0, 58.0], [21.0, 57.0]]
    ]
    # Stated counter-clockwise already: not reversed, so no orientation note.
    assert T["IGEOLO ring orientation"] not in south_up["source"]["transformations"]


def test_utc_reformatting_is_recorded_only_when_a_date_was_rendered():
    as_of = AsOf("2026-01-02T03:04:05Z", "exercise context instant")
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001", as_of=as_of)
    objects = translate(geo_with(FDT=b" " * 14, IDATIM=b" " * 14), context=context)
    record = objects[0]["attributes"]["stanag4545"]
    assert record["product_time"] is None and record["images"][0]["capture_time"] is None
    assert objects[0]["source"]["transformations"] == [
        T["ASCII display trimming"],
        T["date fallback"] + " Basis: exercise context instant",
        T["integer conversion"],
    ]
    assert objects[1]["source"]["transformations"] == [
        T["ASCII display trimming"],
        T["IGEOLO corner coordinates"],
        T["IGEOLO ring orientation"],
    ]


# --------------------------------------------------------------------------- residual edges

#: One TRE of three data octets (6 + 5 + 3 = 14 octets) and the area holding it: L = 3 + 14 =
#: 17, the overflow number 000, then the TRE.
AREA_TRE = b"SCAREA" + b"00003" + b"abc"
AREA = b"00017" + b"000" + AREA_TRE


def _with_file_areas(raw: bytes, udhd: bytes, xhd: bytes) -> bytes:
    """`raw` with its two empty file areas (the last ten octets before HL) replaced."""
    hl = int(raw[354:360])
    assert raw[hl - 10 : hl] == b"0000000000"
    out = bytearray(raw[: hl - 10] + udhd + xhd + raw[hl:])
    out[354:360] = KIT.d(hl - 10 + len(udhd) + len(xhd), 6)
    out[342:354] = KIT.d(len(out), 12)
    return bytes(out)


def _text_sh(area: bytes) -> bytes:
    a = KIT.a
    return (
        b"TE"
        + a("TXT001", 7)
        + b"000"
        + b"20261004120000"
        + a("SYNTHETIC TEXT", 80)
        + KIT.sec()
        + b"0"
        + b"STA"
        + area
    )


def _area_container(name: str) -> bytes:
    image = KIT.image()
    if name in ("UDHD", "XHD"):
        plain = KIT.container([image])
        return _with_file_areas(
            plain, AREA if name == "UDHD" else b"00000", AREA if name == "XHD" else b"00000"
        )
    if name == "UDID":
        subheader, pixels = image
        # UDIDL is the tenth octet from the end of the subheader; IXSHDL the last five.
        return KIT.container([(subheader[:-10] + AREA + subheader[-5:], pixels)])
    if name == "IXSHD":
        return KIT.container([KIT.image(tre=AREA_TRE)])
    if name == "SXSHD":
        return KIT.container([image], others=[("S", graphic_sh(2, 1)[:-5] + AREA, b"abc")])
    return KIT.container([image], others=[("T", _text_sh(AREA), b"hello")])


#: Where each area's three fields sit, derived from the field widths: (group, length field and
#: its offset, overflow field and its offset, body field and its offset). The file areas follow
#: the directory of a one-image file (UDHDL at 394, XHDL at 399); the image areas the 439-octet
#: subheader at 404 (UDIDL at 833, IXSHDL at 838); a graphic subheader after an image (HL 414,
#: image 414 to 853, four data octets) starts at 857 with SXSHDL at 857 + 253; a text subheader
#: after an image (HL 413, data to 856) starts at 856 with TXSHDL at 856 + 277.
AREA_RECORDS = {
    "UDHD": ("file", ("UDHDL", 394), ("UDHOFL", 399), ("UDHD", 402)),
    "XHD": ("file", ("XHDL", 399), ("XHDLOFL", 404), ("XHD", 407)),
    "UDID": ("image", ("UDIDL", 833), ("UDOFL", 838), ("UDID", 841)),
    "IXSHD": ("image", ("IXSHDL", 838), ("IXSOFL", 843), ("IXSHD", 846)),
    "SXSHD": ("graphic", ("SXSHDL", 1110), ("SXSOFL", 1115), ("SXSHD", 1118)),
    "TXSHD": ("text", ("TXSHDL", 1133), ("TXSOFL", 1138), ("TXSHD", 1141)),
}


@pytest.mark.parametrize("name", sorted(AREA_RECORDS))
def test_each_non_empty_extension_area_records_its_overflow_number_and_its_body(name):
    group, (length_name, at), (overflow_name, overflow_at), (body_name, body_at) = AREA_RECORDS[
        name
    ]
    record = residual(translate(_area_container(name)))
    if group == "file":
        fields = record["file_header"]["fields"]
    else:
        fields = next(s for s in record["segments"] if s["kind"] == group)["fields"]
    assert fields[length_name] == {"offset": at, "length": 5, "text": "00017"}
    assert fields[overflow_name] == {"offset": overflow_at, "length": 3, "text": "000"}
    assert fields[body_name] == {"offset": body_at, "length": 14}
    names = list(fields)
    position = names.index(length_name)
    assert names[position : position + 3] == [length_name, overflow_name, body_name]
    assert [(e["area"], e["tag"], e["offset"], e["length"]) for e in record["extensions"]] == [
        (name, "SCAREA", body_at, 14)
    ]


def test_an_empty_extension_area_contributes_only_its_length_field():
    record = residual(translate(vector("mono_nsif101.ntf")))
    header = record["file_header"]["fields"]
    image = record["segments"][0]["fields"]
    assert header["UDHDL"] == {"offset": 394, "length": 5, "text": "00000"}
    assert header["XHDL"] == {"offset": 399, "length": 5, "text": "00000"}
    assert image["UDIDL"] == {"offset": 833, "length": 5, "text": "00000"}
    assert image["IXSHDL"] == {"offset": 838, "length": 5, "text": "00000"}
    for absent in ("UDHOFL", "UDHD", "XHDLOFL", "XHD"):
        assert absent not in header
    for absent in ("UDOFL", "UDID", "IXSOFL", "IXSHD"):
        assert absent not in image


#: The assessment of geo_dms with one label field made non-printable: a null CLAS is not one of
#: the five letters, is a value of its own for `uniform_clas`, is left out of `clas_values`; a
#: null CODE is not empty, so it is a caveat.
NULL_LABEL_CASES = (
    (
        ((FILE_SEC, "CLAS"),),
        ["CLAS_UNRECOGNISED", "LABEL_FIELD_UNINTERPRETED"],
        ["U"],
        False,
    ),
    (
        ((FILE_SEC, "CLAS"), (IMAGE_SEC, "CLAS")),
        ["CLAS_UNRECOGNISED", "LABEL_FIELD_UNINTERPRETED"],
        [],
        True,
    ),
    (
        ((IMAGE_SEC, "CODE"),),
        ["LABEL_FIELD_UNINTERPRETED", "RESTRICTIVE_CAVEAT"],
        ["U"],
        True,
    ),
)


@pytest.mark.parametrize("changes, reasons, clas_values, uniform", NULL_LABEL_CASES)
def test_a_null_label_field_is_assessed_as_its_own_value(changes, reasons, clas_values, uniform):
    raw = vector("geo_dms.ntf")
    for block, name in changes:
        raw = patch(raw, block + SEC_FIELDS[name][0], b"\xff")
    expected = {
        "status": "unresolved",
        "reasons": reasons,
        "scopes": 2,
        "clas_values": clas_values,
        "uniform_clas": uniform,
        "unknown_extensions": {"tre": 0, "des": 0, "res": 0},
        "combination": "not_performed",
        "kind": "core_assessment",
    }
    objects = translate(raw)
    assert residual(objects)["security"]["assessment"] == expected
    assert residual(objects, 1)["security"]["assessment"] == expected


#: An FDT that is not a valid instant, by status: each falls back to the supplied as_of, records
#: the fallback, and without an as_of is the context refusal.
FDT_FALLBACKS = (
    (b"2026100412000Z", "DATE_MALFORMED"),
    (b"20261004120---", "DATE_PARTIAL"),
    (b"20261004125960", "TIME_UNRESOLVED"),
    (b"00000000000000", "DATE_UNKNOWN"),
)


@pytest.mark.parametrize("fdt, code", FDT_FALLBACKS)
def test_every_fdt_that_is_not_an_instant_falls_back_to_as_of(fdt, code):
    as_of = AsOf("2026-01-02T03:04:05Z", "exercise context instant")
    raw = mono_with(FDT=fdt)
    keyed = Stanag4545Context(product_key="EXERCISE-CASES-0001")
    error = refusal(adapter(context=keyed).to_cdm, raw)
    assert coded(error) == ("E_CONTEXT", "cdm", None, "/context/as_of")
    context = Stanag4545Context(product_key="EXERCISE-CASES-0001", as_of=as_of)
    objects = translate(raw, context=context)
    assert objects[0]["valid_from"] == "2026-01-02T03:04:05.000Z"
    record = objects[0]["attributes"]["stanag4545"]
    assert record["product_time"] is None
    assert [(d["code"], d["stage"], d["offset"], d["path"]) for d in record["diagnostics"]] == [
        (code, "header", 25, "/file_header/FDT")
    ]
    assert (
        T["date fallback"] + " Basis: exercise context instant"
        in (objects[0]["source"]["transformations"])
    )


def test_background_colour_octets_above_127_stay_unsigned():
    raw = patch(vector("mono_nsif101.ntf"), 297, b"\xff\x80\x01")
    assert residual(translate(raw))["file_header"]["fields"]["FBKGC"] == {
        "offset": 297,
        "length": 3,
        "values": [255, 128, 1],
    }


@pytest.mark.parametrize("character", ["\t", "\n", "\x00", "\x1f", "\x7f", "\xa0"])
@pytest.mark.parametrize("field", ["dataset_namespace", "product_key", "asset_ref"])
def test_a_context_identifier_with_a_control_character_or_del_is_refused(field, character):
    with pytest.raises(ValueError):
        Stanag4545Context(**{field: f"exercise{character}one"})
    # The printable neighbours are accepted.
    assert getattr(Stanag4545Context(**{field: "exercise ~ one"}), field) == "exercise ~ one"


def test_no_two_returned_objects_and_no_parse_record_share_a_mutable_value(monkeypatch):
    seen = []

    def parse_and_keep(raw, limits):
        found = nsif_codec.parse_container(raw, limits)
        seen.append(found)
        return found

    monkeypatch.setattr(module, "parse_container", parse_and_keep)
    objects = adapter().to_cdm(vector("geo_dms.ntf"))
    product = objects[0].residual.data["stanag4545"]
    footprint = objects[1].residual.data["stanag4545"]
    assert footprint["image"] == product["segments"][0]
    assert footprint["image"] is not product["segments"][0]
    for index in (0, 1):
        assert footprint["security"]["labels"][index] == product["security"]["labels"][index]
        assert footprint["security"]["labels"][index] is not product["security"]["labels"][index]
    assert footprint["security"]["assessment"] is not product["security"]["assessment"]
    # The PlanObject validates the parse record's geometry into a model of its own, so it holds
    # no reference to the record's dict.
    record = seen[-1].images[0].footprint.geometry
    assert objects[1].geometry.model_dump(mode="json") == record
    assert objects[1].geometry is not record


def test_every_footprint_names_the_count_of_images_in_its_product():
    # geo_dms's image twice, the second with its corners one degree further east: two
    # footprints, each naming its own image and the product's two images.
    subheader, pixels = KIT.image(geo=GEO)
    east = "480000N0180000E480000N0190000E470000N0190000E470000N0180000E"
    objects = translate(KIT.container([(subheader, pixels), KIT.image(geo=east)]))
    assert len(objects) == 3
    assert [residual(objects, k)["image"]["index"] for k in (1, 2)] == [0, 1]
    assert [residual(objects, k)["product"]["image_count"] for k in (1, 2)] == [2, 2]
    assert residual(translate(vector("geo_dms.ntf")), 1)["product"]["image_count"] == 1
