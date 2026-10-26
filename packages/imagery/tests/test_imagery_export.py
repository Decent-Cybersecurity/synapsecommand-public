"""The experimental SC4545-WRITE-NC8-1 writer: the recipe's three validation passes with literal
codes and paths, the fixed layout against the kit's vectors and hand-derived offsets, corner
rounding, the self-check before anything is written, and the provenance committed first."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import pathlib

import jsonschema
import pytest
from conftest import LOCAL
from helpers import ruled_export_id, sha, vector

from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container
from synapse_cdm.version import PACKAGE_VERSION
from synapse_imagery import export
from synapse_imagery import ingest as ingest_module
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.policy import Artefact, Principal
from synapse_imagery.result import HostError

MONO_SAMPLES = bytes([0, 64, 128, 255])
KIT_CORNERS = {
    "ul": {"lat": "48", "lon": "17"},
    "ur": {"lat": "48", "lon": "18"},
    "lr": {"lat": "47", "lon": "18"},
    "ll": {"lat": "47", "lon": "17"},
}
# Digits of other scripts, written as code points: fullwidth (U+FF10..U+FF19) and Arabic-Indic
# (U+0660..U+0669).
FULLWIDTH_2026 = "\uff12\uff10\uff12\uff16"
ARABIC_2026 = "\u0662\u0660\u0662\u0666"
FULLWIDTH_48 = "\uff14\uff18"
FULLWIDTH_17 = "\uff11\uff17"
ARABIC_18 = "\u0661\u0668"
ARABIC_47 = "\u0664\u0667"
QUALIFICATION = (
    "experimental engineering output: not independently parsed, not checked clause by clause "
    "against a normative profile; a self-parse accepting its own file is necessary and "
    "insufficient"
)


def recipe(**changes) -> dict:
    out = {
        "recipe": "SC4545-WRITE-NC8-1",
        "producer_id": "SCFIX",
        "product_id": "SCFIX0001",
        "product_time": "2026-10-04T12:00:00Z",
        "capture_time": "2026-10-04T12:00:00Z",
        "source_attribution": "SYNTHETIC",
        "security": {"classification": "U"},
        "raster": {
            "representation": "MONO",
            "width": 2,
            "height": 2,
            "bits": 8,
            "samples_b64": base64.b64encode(MONO_SAMPLES).decode("ascii"),
        },
    }
    for key, value in changes.items():
        if value is None:
            del out[key]
        else:
            out[key] = value
    return out


def raster(**changes) -> dict:
    out = recipe()["raster"]
    for key, value in changes.items():
        if value is None:
            del out[key]
        else:
            out[key] = value
    return out


def refusal(data) -> tuple:
    text = data if isinstance(data, bytes) else json.dumps(data).encode("ascii")
    with pytest.raises(HostError) as caught:
        export.read_recipe(text)
    error = caught.value
    return error.code, error.stage, error.offset, error.path


# --------------------------------------------------------------------------- pass 1: unsupported


@pytest.mark.parametrize(
    "document, path",
    [
        (recipe(magic="NSIF01.00"), "/recipe/magic"),
        (recipe(raster=raster(bits=16)), "/recipe/raster/bits"),
        (recipe(raster=raster(representation="MULTI")), "/recipe/raster/representation"),
        (recipe(raster=raster(bands=4)), "/recipe/raster/representation"),
        (recipe(raster=raster(width=2049)), "/recipe/raster/width"),
        (recipe(raster=raster(height=4096)), "/recipe/raster/height"),
        (recipe(tres=[]), "/recipe/tres"),
        (recipe(copy_tres=True), "/recipe/tres"),
        (recipe(jpeg_tables="x"), "/recipe/compression"),
        (recipe(compression="C3"), "/recipe/compression"),
        (recipe(transformations=["crop"]), "/recipe/transformations"),
        (recipe(crop=[0, 0, 1, 1]), "/recipe/transformations"),
        (recipe(resample=2), "/recipe/transformations"),
        (recipe(rpc={}), "/recipe/sensor_model"),
        (recipe(ichipb={}), "/recipe/sensor_model"),
        (recipe(blocka={}), "/recipe/sensor_model"),
        (recipe(sensor_model="RPC00B"), "/recipe/sensor_model"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_a_request_for_what_the_writer_does_not_do_is_unsupported(document, path):
    assert refusal(document) == ("E_PROFILE", "export", None, path)


# --------------------------------------------------------------------------- pass 2: security


@pytest.mark.parametrize(
    "security",
    [
        {"classification": "R"},
        {"classification": "U", "REL": "X"},
        {"classification": "U", "CODE": "AB"},
        {"classification": "U", "CTLH": "X"},
        {},
        "U",
    ],
)
def test_anything_but_plain_unclassified_is_a_policy_refusal(security):
    assert refusal(recipe(security=security)) == ("E_POLICY", "export", None, "/recipe/security")


def test_unsupported_features_are_decided_before_security():
    document = recipe(security={"classification": "S"}, magic="NSIF01.00")
    assert refusal(document)[0] == "E_PROFILE"


# --------------------------------------------------------------------------- pass 3: the schema


@pytest.mark.parametrize(
    "document, path",
    [
        (recipe(capture_time=None), "/recipe/capture_time"),
        (recipe(producer_id="SCFIX0001"), "/recipe/producer_id"),
        (recipe(product_id="SCFIX000001"), "/recipe/product_id"),
        (recipe(source_attribution="S" * 43), "/recipe/source_attribution"),
        (recipe(product_time="2026-10-04 12:00:00"), "/recipe/product_time"),
        (recipe(recipe="SC4545-WRITE-NC16-1"), "/recipe/recipe"),
        (recipe(magic="NITF02.00"), "/recipe/magic"),
        (recipe(title="x"), "/recipe"),
        (recipe(transformations=[]), "/recipe"),
        (recipe(raster=raster(width=0)), "/recipe/raster/width"),
        (recipe(raster=raster(width="2")), "/recipe/raster/width"),
        (recipe(raster=raster(samples_b64=None)), "/recipe/raster/samples_b64"),
        (recipe(raster=raster(samples_b64="AA AA")), "/recipe/raster/samples_b64"),
        (recipe(corners={"ul": KIT_CORNERS["ul"]}), "/recipe/corners/ur"),
        (
            recipe(corners={**KIT_CORNERS, "ul": {"lat": "48.0000000000001", "lon": "17"}}),
            "/recipe/corners/ul/lat",
        ),
        (recipe(parent={"record_id": "not-a-uuid"}), "/recipe/parent/record_id"),
        (recipe(security=None), "/recipe/security"),
    ],
)
def test_the_first_schema_error_names_its_path(document, path):
    assert refusal(document) == ("E_FIELD", "export", None, path)


def test_the_schema_is_a_valid_closed_2020_12_schema():
    jsonschema.Draft202012Validator.check_schema(export.SCHEMA)

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)

    found = list(objects(export.SCHEMA))
    assert len(found) == 6
    assert all(node["additionalProperties"] is False for node in found)


# --------------------------------------------------------------------------- the semantic checks


@pytest.mark.parametrize(
    "document, code, path",
    [
        (recipe(capture_time="2026-06-30T23:59:60Z"), "E_FIELD", "/recipe/capture_time"),
        (recipe(product_time="2026-02-30T00:00:00Z"), "E_FIELD", "/recipe/product_time"),
        (recipe(product_time="2026-13-01T00:00:00Z"), "E_FIELD", "/recipe/product_time"),
        (recipe(product_time="0000-01-01T00:00:00Z"), "E_FIELD", "/recipe/product_time"),
        (recipe(producer_id=" SCFIX"), "E_FIELD", "/recipe/producer_id"),
        (recipe(product_id="SCé"), "E_FIELD", "/recipe/product_id"),
        (recipe(source_attribution="A\tB"), "E_FIELD", "/recipe/source_attribution"),
        (
            recipe(raster=raster(samples_b64=base64.b64encode(MONO_SAMPLES[:3]).decode())),
            "E_LENGTH",
            "/recipe/raster/samples_b64",
        ),
        (
            recipe(raster=raster(samples_b64=base64.b64encode(bytes(5)).decode())),
            "E_LENGTH",
            "/recipe/raster/samples_b64",
        ),
        (
            recipe(raster=raster(width=1, height=1, samples_b64="AB==")),
            "E_FIELD",
            "/recipe/raster/samples_b64",
        ),
        (
            recipe(raster=raster(samples_b64="AEC")),
            "E_FIELD",
            "/recipe/raster/samples_b64",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ul": {"lat": "90.0001", "lon": "17"}}),
            "E_FIELD",
            "/recipe/corners/ul/lat",
        ),
        (
            recipe(corners={**KIT_CORNERS, "lr": {"lat": "47", "lon": "-180.5"}}),
            "E_FIELD",
            "/recipe/corners/lr/lon",
        ),
        # The schema's patterns are searched, so `$` admits a final newline and `\d` admits
        # the digits of every script: times and corners are matched again in ASCII, whole.
        (recipe(product_time="2026-10-04T12:00:00Z\n"), "E_FIELD", "/recipe/product_time"),
        (recipe(capture_time="2026-10-04T12:00:00Z\n"), "E_FIELD", "/recipe/capture_time"),
        (
            recipe(product_time=f"{FULLWIDTH_2026}-10-04T12:00:00Z"),
            "E_FIELD",
            "/recipe/product_time",
        ),
        (
            recipe(capture_time=f"{FULLWIDTH_2026}-10-04T12:00:00Z"),
            "E_FIELD",
            "/recipe/capture_time",
        ),
        (recipe(product_time=f"{ARABIC_2026}-10-04T12:00:00Z"), "E_FIELD", "/recipe/product_time"),
        (recipe(capture_time=f"{ARABIC_2026}-10-04T12:00:00Z"), "E_FIELD", "/recipe/capture_time"),
        (
            recipe(corners={**KIT_CORNERS, "ul": {"lat": "48\n", "lon": "17"}}),
            "E_FIELD",
            "/recipe/corners/ul/lat",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ul": {"lat": "48", "lon": "17\n"}}),
            "E_FIELD",
            "/recipe/corners/ul/lon",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ur": {"lat": FULLWIDTH_48, "lon": "18"}}),
            "E_FIELD",
            "/recipe/corners/ur/lat",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ur": {"lat": "48", "lon": ARABIC_18}}),
            "E_FIELD",
            "/recipe/corners/ur/lon",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ll": {"lat": ARABIC_47, "lon": "17"}}),
            "E_FIELD",
            "/recipe/corners/ll/lat",
        ),
        (
            recipe(corners={**KIT_CORNERS, "ll": {"lat": "47", "lon": FULLWIDTH_17}}),
            "E_FIELD",
            "/recipe/corners/ll/lon",
        ),
    ],
)
def test_what_a_schema_cannot_say_is_checked_after_it(document, code, path):
    assert refusal(document) == (code, "export", None, path)


def test_the_capture_time_is_required_even_with_a_product_time():
    document = recipe(capture_time=None)
    assert refusal(document)[3] == "/recipe/capture_time"


@pytest.mark.parametrize(
    "data",
    [
        b'{"recipe": "a", "recipe": "b"}',
        b"[1, 2]",
        b'"recipe"',
        b"[" * 100_000,
        b"\xff\xfe{}",
        b'{"recipe": NaN}',
        b"",
        b" " * (33_554_432 + 1),
    ],
    ids=["duplicate", "array", "string", "deep", "not-utf8", "nan", "empty", "over-cap"],
)
def test_a_document_that_is_not_one_plain_object_is_refused(data):
    assert refusal(data) == ("E_FIELD", "export", None, "/recipe")


# --------------------------------------------------------------------------- the layout


def masked(octets: bytes) -> bytes:
    out = bytearray(octets)
    for start, end in ((39, 119), (300, 324), (447, 527)):
        out[start:end] = bytes(end - start)
    return bytes(out)


@pytest.mark.parametrize(
    "changes, kit",
    [
        ({}, "mono_nsif101.ntf"),
        ({"magic": "NITF02.10"}, "mono_nitf210.ntf"),
        ({"corners": KIT_CORNERS}, "geo_dms.ntf"),
    ],
)
def test_the_layout_matches_the_kit_outside_three_descriptive_fields(changes, kit):
    written = export.write_nc8(export.read_recipe(json.dumps(recipe(**changes)).encode()))
    octets = written.octets
    assert masked(octets) == masked(vector(kit))
    assert octets[39:119] == b"SCFIX0001" + b" " * 71
    assert octets[300:324] == b" " * 24
    assert octets[447:527] == b" " * 80
    assert written.provenance["output"] == {
        "sha256": hashlib.sha256(octets).hexdigest(),
        "bytes": len(octets),
        "magic": changes.get("magic", "NSIF01.01"),
    }


def test_an_rgb_raster_has_three_descriptors_in_order_and_its_lengths():
    samples = bytes(range(18))
    document = recipe(
        raster=raster(
            representation="RGB", width=3, height=2, samples_b64=base64.b64encode(samples).decode()
        )
    )
    octets = export.write_nc8(export.read_recipe(json.dumps(document).encode())).octets
    # Hand-derived: HL 404; LISH 439 + 2 x 13 for the two extra band descriptors; LI 18.
    assert len(octets) == 887
    assert (octets[342:354], octets[354:360], octets[360:363]) == (
        b"000000000887",
        b"000404",
        b"001",
    )
    assert (octets[363:369], octets[369:379]) == (b"000465", b"0000000018")
    assert octets[756:764] == b"RGB     " and octets[779:780] == b"3"
    assert [octets[at : at + 13] for at in (780, 793, 806)] == [
        b"R       N   0",
        b"G       N   0",
        b"B       N   0",
    ]
    assert octets[-18:] == samples
    # NPPBH and NPPBV follow ISYNC, IMODE, NBPR and NBPC after the third descriptor (819).
    assert octets[819:837] == b"0B00010001" + b"0003" + b"0002"


def test_every_fixed_value_of_the_mono_layout():
    octets = export.write_nc8(export.read_recipe(json.dumps(recipe()).encode())).octets
    fixed = {
        (0, 9): b"NSIF01.01",
        (9, 11): b"03",
        (11, 15): b"BF01",
        (15, 25): b"SCFIX     ",
        (25, 39): b"20261004120000",
        (119, 286): b"U" + b" " * 166,
        (286, 296): b"0000000000",
        (296, 297): b"0",
        (297, 300): bytes(3),
        (324, 342): b" " * 18,
        (379, 404): b"000" * 5 + b"0000000000",
        (404, 406): b"IM",
        (406, 416): b"SCFIX0001 ",
        (416, 430): b"20261004120000",
        (430, 447): b" " * 17,
        (527, 694): b"U" + b" " * 166,
        (694, 695): b"0",
        (695, 737): b"SYNTHETIC" + b" " * 33,
        (737, 753): b"0000000200000002",
        (753, 756): b"INT",
        (756, 764): b"MONO    ",
        (764, 772): b"VIS     ",
        (772, 775): b"08R",
        (775, 776): b" ",
        (776, 780): b"0NC1",
        (780, 793): b"M       N   0",
        (793, 795): b"0B",
        (795, 803): b"00010001",
        (803, 811): b"00020002",
        (811, 813): b"08",
        (813, 819): b"001000",
        (819, 829): b"0000000000",
        (829, 833): b"1.0 ",
        (833, 843): b"0000000000",
        (843, 847): MONO_SAMPLES,
    }
    for (start, end), value in fixed.items():
        assert octets[start:end] == value, (start, end)
    assert len(octets) == 847


@pytest.mark.parametrize(
    "value, digits, emitted, delta",
    [
        ("48.99999", 2, "490000N", "+0.036"),
        ("-48.99999", 2, "490000S", "-0.036"),
        ("-0.0001", 2, "000000N", "+0.36"),
        ("48", 2, "480000N", "+0"),
        ("48.0001388888", 2, "480000N", "-0.49999968"),
        ("48.000138889", 2, "480001N", "+0.4999996"),
        ("89.99999", 2, "900000N", "+0.036"),
        ("179.99999", 3, "1800000E", "+0.036"),
        ("-17.5", 3, "0173000W", "+0"),
        ("0.0001389", 3, "0000001E", "+0.49996"),
    ],
)
def test_corners_round_to_the_nearest_arcsecond_with_carry_and_record_it(
    value, digits, emitted, delta
):
    hemispheres = ("N", "S") if digits == 2 else ("E", "W")
    text, recorded, _ = export._corner(value, digits, *hemispheres)
    assert (text, recorded) == (emitted, delta)


def corners(**changes):
    out = copy.deepcopy(KIT_CORNERS)
    for name, value in changes.items():
        out[name] = value
    return out


def test_the_rounding_of_every_corner_is_in_the_provenance():
    document = recipe(
        corners=corners(ul={"lat": "48.99999", "lon": "17"}, ur={"lat": "48.99999", "lon": "18"})
    )
    written = export.write_nc8(export.read_recipe(json.dumps(document).encode()))
    assert written.provenance["corner_rounding"][:2] == [
        {
            "corner": "ul",
            "lat": "48.99999",
            "lon": "17",
            "emitted": "490000N0170000E",
            "lat_delta_arcseconds": "+0.036",
            "lon_delta_arcseconds": "+0",
        },
        {
            "corner": "ur",
            "lat": "48.99999",
            "lon": "18",
            "emitted": "490000N0180000E",
            "lat_delta_arcseconds": "+0.036",
            "lon_delta_arcseconds": "+0",
        },
    ]
    assert written.octets[776:836] == (
        b"490000N0170000E490000N0180000E470000N0180000E470000N0170000E"
    )


def test_a_corner_rounded_onto_a_pole_is_refused_by_the_footprint_check():
    document = recipe(corners=corners(ul={"lat": "89.99999", "lon": "17"}))
    with pytest.raises(HostError) as caught:
        export.write_nc8(export.read_recipe(json.dumps(document).encode()))
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_FIELD",
        "export",
        "/recipe/corners",
    )


def test_a_southern_footprint_is_written():
    document = recipe(
        corners={
            "ul": {"lat": "-47", "lon": "17"},
            "ur": {"lat": "-47", "lon": "18"},
            "lr": {"lat": "-48.99999", "lon": "18"},
            "ll": {"lat": "-48.99999", "lon": "17"},
        }
    )
    written = export.write_nc8(export.read_recipe(json.dumps(document).encode()))
    assert written.octets[776:836] == (
        b"470000S0170000E470000S0180000E490000S0180000E490000S0170000E"
    )
    container = parse_container(written.octets, CORE1_LIMITS)
    assert container.images[0].geometry_status == "available"
    assert [entry["lat_delta_arcseconds"] for entry in written.provenance["corner_rounding"]] == [
        "+0",
        "+0",
        "-0.036",
        "-0.036",
    ]


def test_the_self_check_refuses_a_defective_serialiser(monkeypatch, services, store, tmp_path):
    original = export._serialise
    monkeypatch.setattr(export, "_serialise", lambda *args: original(*args)[:-1])
    with pytest.raises(HostError) as caught:
        export.write_nc8(export.read_recipe(json.dumps(recipe()).encode()))
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_INTERNAL",
        "export",
        "/self_check/parse",
    )
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe()))
    service = services(store, worker=InProcessWorker())
    with pytest.raises(HostError):
        service.export_nc(path, tmp_path / "out.ntf", principal=LOCAL)
    assert not (tmp_path / "out.ntf").exists()
    assert list(pathlib.Path(store.root, "tenants").glob("*/exports/*")) == []


def test_a_writer_that_lost_its_samples_is_caught_by_the_sample_check(monkeypatch):
    original = export._serialise

    def flipped(recipe_fields, igeolo, samples):
        return original(recipe_fields, igeolo, bytes(len(samples)))

    monkeypatch.setattr(export, "_serialise", flipped)
    with pytest.raises(HostError) as caught:
        export.write_nc8(export.read_recipe(json.dumps(recipe()).encode()))
    assert caught.value.path == "/self_check/samples"


# --------------------------------------------------------------------------- the export operation


def write_recipe(tmp_path, document, name="recipe.json") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def export_records(store) -> list[pathlib.Path]:
    return sorted(pathlib.Path(store.root, "tenants").glob("*/exports/*.json"))


def test_an_export_commits_its_provenance_and_delivers_its_file(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    output = tmp_path / "out.ntf"
    receipt = service.export_nc(write_recipe(tmp_path, recipe()), output, principal=LOCAL)
    octets = output.read_bytes()
    assert masked(octets) == masked(vector("mono_nsif101.ntf"))
    recipe_sha256 = hashlib.sha256(
        json.dumps(recipe(), sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    export_id = ruled_export_id("local", recipe_sha256, sha(octets))
    assert receipt == {
        "schema": "sc-imagery-export/1",
        "export_id": export_id,
        "output_sha256": sha(octets),
        "bytes": 847,
        "magic": "NSIF01.01",
        "writer": "SC4545-WRITE-NC8-1",
        "status": "experimental",
    }
    (path,) = export_records(store)
    assert path.name == f"{export_id}.json"
    assert os.stat(path).st_mode & 0o777 == 0o400
    stored = json.loads(path.read_text())
    stored_recipe = recipe()
    stored_recipe["raster"] = {
        "representation": "MONO",
        "width": 2,
        "height": 2,
        "bits": 8,
        "samples_sha256": sha(MONO_SAMPLES),
        "samples_bytes": 4,
    }
    assert stored == {
        "format": "sc-imagery-export-record/1",
        "writer": "SC4545-WRITE-NC8-1",
        "writer_version": "1.0.0",
        "status": "experimental",
        "qualification": QUALIFICATION,
        "recipe": stored_recipe,
        "recipe_sha256": recipe_sha256,
        "parent": None,
        "output": {"sha256": sha(octets), "bytes": 847, "magic": "NSIF01.01"},
        "lossy_transformations": [],
        "samples": "preserved_exactly",
        "container": "newly_authored",
        "corner_rounding": [],
        "self_check": {
            "parse": "ok",
            "samples_equal": True,
            "length_equal": True,
            "security_status": "declared_unclassified",
            "validate_source": [],
        },
        "software": {"synapse_imagery": "1.0.0", "synapse_cdm": PACKAGE_VERSION},
    }
    assert os.listdir(pathlib.Path(store.root) / "staging") == []
    assert os.stat(output).st_mode & 0o777 == 0o600


def test_an_export_with_a_parent_names_its_parent(services, store, tmp_path):
    octets = vector("geo_dms.ntf")
    service = services(store, worker=InProcessWorker())
    parent = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    document = recipe(parent={"record_id": parent["record_id"]}, corners=KIT_CORNERS)
    service.export_nc(write_recipe(tmp_path, document), tmp_path / "out.ntf", principal=LOCAL)
    (path,) = export_records(store)
    stored = json.loads(path.read_text())
    assert stored["parent"] == {
        "record_id": parent["record_id"],
        "asset_id": parent["asset_id"],
        "sha256": sha(octets),
    }
    assert [entry["emitted"] for entry in stored["corner_rounding"]] == [
        "480000N0170000E",
        "480000N0180000E",
        "470000N0180000E",
        "470000N0170000E",
    ]


def test_a_parent_of_another_tenant_is_answered_as_an_unknown_one(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    parent = service.ingest(
        vector("mono_nsif101.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    document = recipe(parent={"record_id": parent["record_id"]})
    with pytest.raises(HostError) as caught:
        service.export_nc(
            write_recipe(tmp_path, document), tmp_path / "out.ntf", principal=Principal("t2", "a")
        )
    assert str(caught.value) == (
        "E_FIELD @byte - /recipe/parent/record_id: "
        "no committed record with this id for this principal"
    )
    assert caught.value.stage == "export"
    assert not (tmp_path / "out.ntf").exists() and export_records(store) == []


def test_a_policy_denying_the_export_refuses_it(services, store, tmp_path):
    allow = FakePolicy({artefact: True for artefact in Artefact if artefact is not Artefact.EXPORT})
    service = services(store, worker=InProcessWorker(), policy=allow)
    parent = service.ingest(
        vector("mono_nsif101.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    document = recipe(parent={"record_id": parent["record_id"]})
    with pytest.raises(HostError) as caught:
        service.export_nc(write_recipe(tmp_path, document), tmp_path / "out.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/export")
    assert not (tmp_path / "out.ntf").exists() and export_records(store) == []


def test_a_failed_delivery_leaves_the_record_of_an_undelivered_export(
    monkeypatch, services, store, tmp_path
):
    def refuse(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(ingest_module, "_deliver", refuse)
    service = services(store, worker=InProcessWorker())
    with pytest.raises(OSError):
        service.export_nc(write_recipe(tmp_path, recipe()), tmp_path / "out.ntf", principal=LOCAL)
    assert not (tmp_path / "out.ntf").exists()
    assert len(export_records(store)) == 1


def test_a_rerun_is_idempotent(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    path = write_recipe(tmp_path, recipe())
    first = service.export_nc(path, tmp_path / "out.ntf", principal=LOCAL)
    # The same recipe in another key order and spacing is the same recipe.
    reordered = tmp_path / "again.json"
    reordered.write_text(json.dumps(dict(reversed(list(recipe().items()))), indent=3))
    second = service.export_nc(reordered, tmp_path / "out.ntf", principal=LOCAL, replace=True)
    assert first == second
    assert len(export_records(store)) == 1


def test_an_existing_output_is_refused_before_the_recipe_is_read(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    output = tmp_path / "out.ntf"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        service.export_nc(tmp_path / "absent.json", output, principal=LOCAL)
    assert output.read_bytes() == b"keep"


@pytest.mark.parametrize("make", ["absent", "directory", "fifo"])
def test_a_recipe_that_is_not_a_regular_file_is_an_io_error(services, store, tmp_path, make):
    path = tmp_path / "recipe.json"
    if make == "directory":
        path.mkdir()
    elif make == "fifo":
        os.mkfifo(path)
    service = services(store, worker=InProcessWorker())
    with pytest.raises(HostError) as caught:
        service.export_nc(path, tmp_path / "out.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_IO",
        "input",
        "/recipe",
    )
