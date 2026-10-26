"""The user-visible imagery record: the three exact strings, the stored viewer-neutral record and
the one rebuilt for a viewer's decisions, an absent footprint never shown as a map, and the
inspect document, which carries structure and decisions but never a label value or source
text."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from conftest import LOCAL
from helpers import build_nsif, graphic, image, set_field, sha, vector, with_ic

from synapse_cdm import canonical
from synapse_cdm.adapters.geojson import AsOf
from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container, security_labels
from synapse_imagery import presentation
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.ingest import inspect_source
from synapse_imagery.policy import Artefact, Principal
from synapse_imagery.result import HostError

GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
NOON = "2026-10-04T12:00:00.000Z"


def test_the_three_strings_are_exact():
    assert presentation.FOOTPRINT_LABEL == "imagery footprint"
    assert presentation.PIXELS_UNAVAILABLE == (
        "Image data preserved; this encoding is not supported by this deployment."
    )
    assert presentation.NO_FOOTPRINT == "No usable geographic footprint."
    assert presentation.UNKNOWN == "unknown"


def committed(services, store, octets, **options):
    as_of = options.pop("as_of", None)
    product_key = options.pop("product_key", None)
    service = services(store, worker=InProcessWorker(), **options)
    result = service.ingest(
        octets,
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
        product_key=product_key,
        as_of=as_of,
    )
    assert result["state"] == "committed", result["diagnostics"]
    return service, result


def test_a_located_image_is_shown_with_its_footprint(services, store):
    octets = vector("geo_dms.ntf")
    service, result = committed(services, store, octets)
    shown = service.catalog.presentation(result["record_id"], principal=LOCAL)
    assert shown == {
        "schema": "sc-imagery-presentation/1",
        "source_product_id": result["cdm_ids"][0],
        "wire_signature": "NSIF01.01",
        "file_date": NOON,
        "image_count": 1,
        "images": [
            {
                "index": 0,
                "capture_date": NOON,
                "rows": 2,
                "columns": 2,
                "bands": 1,
                "bits_per_sample": 8,
                "significant_bits": 8,
                "preview": "available",
                "pixel_capability": "native_supported",
                "pixel_message": None,
                "geometry_basis": "IGEOLO",
                "geometry_status": "available",
                "footprint_label": "imagery footprint",
                "geometry_message": None,
                "map": "footprint",
            }
        ],
        "unsupported_content": [],
        "security_display": {
            "authorised": True,
            "status": "declared_unclassified",
            "labels": security_labels(parse_container(octets, CORE1_LIMITS)),
        },
        "derivatives": [],
    }
    labels = shown["security_display"]["labels"]
    assert [(label["scope"], label["offset"], label["fields"]["CLAS"]) for label in labels] == [
        ("file", 119, "U"),
        ("image", 527, "U"),
    ]


def test_an_image_without_corners_is_never_shown_as_a_map(services, store):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    (shown,) = service.catalog.presentation(result["record_id"], principal=LOCAL)["images"]
    assert (
        shown["geometry_status"],
        shown["geometry_message"],
        shown["map"],
        shown["footprint_label"],
        shown["geometry_basis"],
    ) == ("absent", "No usable geographic footprint.", "none", None, None)


@pytest.mark.parametrize(
    "icords, igeolo, status, basis",
    [
        ("G", "486000N" + GEO[7:], "invalid", "IGEOLO"),
        ("G", "900000N" + GEO[7:], "unsupported", "IGEOLO"),
        ("U", GEO, "unsupported", None),
        ("N", GEO, "unsupported", None),
    ],
)
def test_an_unusable_footprint_names_its_basis_and_shows_no_map(
    services, store, icords, igeolo, status, basis
):
    octets = build_nsif([image(icords=icords, igeolo=igeolo)])
    service, result = committed(services, store, octets)
    (shown,) = service.catalog.presentation(result["record_id"], principal=LOCAL)["images"]
    assert (shown["geometry_status"], shown["geometry_basis"]) == (status, basis)
    assert (shown["map"], shown["footprint_label"], shown["geometry_message"]) == (
        "none",
        None,
        "No usable geographic footprint.",
    )


def test_an_unsupported_encoding_says_its_data_is_preserved(services, store):
    service, result = committed(services, store, with_ic(vector("mono_nsif101.ntf"), "C3"))
    shown = service.catalog.presentation(result["record_id"], principal=LOCAL)
    (image_shown,) = shown["images"]
    assert image_shown["pixel_message"] == (
        "Image data preserved; this encoding is not supported by this deployment."
    )
    assert (image_shown["pixel_capability"], image_shown["preview"]) == (
        "unsupported",
        "not_available",
    )
    assert shown["unsupported_content"] == ["image[0]:pixels:compression_not_enabled"]


def test_unknown_dates_are_shown_as_unknown(services, store):
    octets = set_field(vector("mono_nsif101.ntf"), 25, b" " * 14)
    octets = set_field(octets, 416, b" " * 14)
    # Without a valid FDT the product key and the product time both come from the context.
    as_of = AsOf(instant="2026-10-04T12:00:00Z", basis="the operator's stated snapshot instant")
    service, result = committed(
        services, store, octets, as_of=as_of, product_key="EXERCISE-UNKNOWN-DATES-0001"
    )
    shown = service.catalog.presentation(result["record_id"], principal=LOCAL)
    assert shown["file_date"] == "unknown"
    assert shown["images"][0]["capture_date"] == "unknown"


def test_a_preview_appears_as_a_segment_only_derivative(services, store, tmp_path):
    octets = build_nsif([image(icords="G", igeolo=GEO)], graphics=[graphic()])
    service, result = committed(services, store, octets)
    receipt = service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    shown = service.catalog.presentation(result["record_id"], principal=LOCAL)
    assert shown["derivatives"] == [
        {"derivative_id": receipt["derivative_id"], "image_index": 0, "composition": "segment_only"}
    ]
    assert shown["unsupported_content"] == ["graphic:1:not_rendered"]
    # The record stored at commit stays as it was: records are immutable once linked.
    record = store.read_record("local", result["record_id"], area="records")
    assert record["presentation"]["derivatives"] == []


def test_the_stored_record_is_viewer_neutral(services, store):
    octets = vector("geo_dms.ntf")
    service, result = committed(services, store, octets)
    stored = store.read_record("local", result["record_id"], area="records")["presentation"]
    assert stored["source_product_id"] == result["cdm_ids"][0]
    assert stored["security_display"] == {
        "authorised": False,
        "status": "declared_unclassified",
        "labels": None,
    }
    assert stored["images"][0]["preview"] == "not_available"
    assert stored["derivatives"] == []
    assert "SCFIX0001" not in json.dumps(stored) and "480000N" not in json.dumps(stored)


def test_what_a_viewer_sees_follows_its_own_decisions(services, store, tmp_path):
    allow_all = FakePolicy({artefact: True for artefact in Artefact})
    service, result = committed(services, store, vector("geo_dms.ntf"), policy=allow_all)
    service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    no_labels = services(
        store,
        worker=InProcessWorker(),
        policy=FakePolicy({Artefact.THUMBNAIL: True}),
    )
    shown = no_labels.catalog.presentation(result["record_id"], principal=LOCAL)
    assert shown["security_display"] == {
        "authorised": False,
        "status": "declared_unclassified",
        "labels": None,
    }
    assert len(shown["derivatives"]) == 1 and shown["images"][0]["preview"] == "available"
    no_thumbnails = services(
        store, worker=InProcessWorker(), policy=FakePolicy({Artefact.METADATA: True})
    )
    shown = no_thumbnails.catalog.presentation(result["record_id"], principal=LOCAL)
    assert shown["derivatives"] == [] and shown["images"][0]["preview"] == "not_available"
    assert shown["security_display"]["authorised"] is True
    assert shown["security_display"]["labels"][0]["fields"]["CLAS"] == "U"


def test_only_a_committed_record_has_a_presentation(services, store):
    service = services(store, worker=InProcessWorker())
    blocked = service.ingest(
        vector("unknown_duplicate_tre.ntf"),
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
    )
    assert blocked["state"] == "policy_blocked"
    assert (
        store.read_record("local", blocked["record_id"], area="quarantine")["presentation"] is None
    )
    rejected = service.ingest(
        vector("bad_count.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    answers = set()
    for record_id, principal in (
        (blocked["record_id"], LOCAL),
        (rejected["record_id"], LOCAL),
        ("not-a-record", LOCAL),
    ):
        with pytest.raises(HostError) as caught:
            service.catalog.presentation(record_id, principal=principal)
        answers.add(str(caught.value))
    _, committed_result = committed(services, store, vector("mono_nsif101.ntf"))
    with pytest.raises(HostError) as caught:
        service.catalog.presentation(committed_result["record_id"], principal=Principal("t2", "a"))
    answers.add(str(caught.value))
    assert answers == {
        "E_FIELD @byte - /record_id: no committed record with this id for this principal"
    }


def test_labels_are_never_shown_unauthorised():
    inventory = {
        "signature": "NSIF01.01",
        "file_date": {"status": "valid", "utc": NOON},
        "images": [],
        "segments": [],
        "extension_counts": {"tre": 0, "des": 0, "res": 0},
        "composition_status": "segment_only",
        "diagnostics": [],
        "descriptor": None,
    }
    with pytest.raises(ValueError):
        presentation.build(
            inventory,
            product_entity_id=None,
            preview_allowed=False,
            labels_authorised=False,
            labels=[{"scope": "file"}],
            derivatives=[],
        )


# --------------------------------------------------------------------------- the inspect document


def test_the_inspect_document_of_a_valid_file(tmp_path):
    octets = vector("geo_dms.ntf")
    document = inspect_source(octets, worker=InProcessWorker())
    descriptor_free = {key: document[key] for key in document if key not in ("images", "worker")}
    assert descriptor_free["presentation"]["security_display"]["labels"] is None
    assert {key: descriptor_free[key] for key in list(descriptor_free)[:9]} == {
        "schema": "sc-imagery-inspect/1",
        "profile": "SC4545-CORE-1",
        "valid": True,
        "source_bytes": 907,
        "sha256": sha(octets),
        "wire_signature": "NSIF01.01",
        "clevel": 3,
        "file_date": {"status": "valid", "utc": NOON},
        "segments": {"image": 1, "graphic": 0, "text": 0, "des": 0, "res": 0},
    }
    assert document["extensions"] == {"tre": 0, "des": 0, "res": 0}
    assert document["composition_status"] == "segment_only"
    assert document["security"] == {
        "assessment": {
            "status": "declared_unclassified",
            "reasons": [],
            "scopes": 2,
            "clas_values": ["U"],
            "uniform_clas": True,
            "unknown_extensions": {"tre": 0, "des": 0, "res": 0},
            "combination": "not_performed",
            "kind": "core_assessment",
        }
    }
    assert document["policy"] == {
        "policy_id": "sc-imagery-default-clean-u",
        "policy_version": "1",
        "allowed": True,
        "reason": "ADMITTED_DECLARED_UNCLASSIFIED",
        "completeness": "complete",
    }
    assert document["warnings"] == [] and document["diagnostics"] == []
    assert [image["geometry_status"] for image in document["images"]] == ["available"]
    assert document["presentation"]["images"][0]["map"] == "footprint"
    assert document["worker"]["isolation"] == "none"


def test_inspect_warns_when_policy_is_unresolved_and_leaks_no_source_text():
    octets = vector("unknown_duplicate_tre.ntf")
    document = inspect_source(octets, worker=InProcessWorker())
    assert document["valid"] is True
    assert document["warnings"] == ["POLICY_UNRESOLVED"]
    assert document["policy"]["allowed"] is False
    assert document["security"]["assessment"]["status"] == "unresolved"
    assert document["presentation"]["security_display"] == {
        "authorised": False,
        "status": "unresolved",
        "labels": None,
    }
    assert document["presentation"]["unsupported_content"] == ["tre:2:not_interpreted"]
    text = canonical.serialise(document)
    for needle in ("SCFIX0001", "SYNTHETIC", "SYNAPSECOMMAND", "SCZZZZ"):
        assert needle not in text


def test_inspect_of_a_file_the_adapter_refuses_is_the_invalid_document():
    octets = vector("truncated.ntf")
    document = inspect_source(octets, worker=InProcessWorker())
    assert document["valid"] is False
    assert [entry["code"] for entry in document["diagnostics"]] == ["E_LENGTH"]
    assert document["sha256"] == sha(octets) and document["source_bytes"] == len(octets)
    for key in (
        "wire_signature",
        "clevel",
        "file_date",
        "segments",
        "images",
        "extensions",
        "composition_status",
        "security",
        "policy",
        "presentation",
    ):
        assert document[key] is None, key
    assert document["warnings"] == []


def test_inspect_of_a_file_over_the_cap_reads_nothing():
    document = inspect_source(b"N" * 16_777_217, worker=InProcessWorker())
    assert (document["valid"], document["sha256"], document["source_bytes"]) == (
        False,
        None,
        16_777_217,
    )
    assert [(e["code"], e["stage"], e["path"]) for e in document["diagnostics"]] == [
        ("E_LIMIT", "input", "/input")
    ]


def test_inspect_of_a_path_reads_a_regular_file_and_refuses_anything_else(tmp_path):
    path = tmp_path / "geo.ntf"
    path.write_bytes(vector("geo_dms.ntf"))
    assert inspect_source(path, worker=InProcessWorker())["valid"] is True
    os.mkfifo(tmp_path / "fifo")
    for other in (tmp_path / "fifo", tmp_path, tmp_path / "absent"):
        with pytest.raises(HostError) as caught:
            inspect_source(other, worker=InProcessWorker())
        assert (caught.value.code, caught.value.stage, caught.value.path) == (
            "E_IO",
            "input",
            "/input",
        )


def test_inspect_leaves_no_private_directory_behind(tmp_path):
    before = {
        name for name in os.listdir(tempfile.gettempdir()) if name.startswith("sc-imagery-inspect-")
    }
    inspect_source(vector("geo_dms.ntf"))
    inspect_source(vector("truncated.ntf"), worker=InProcessWorker())
    with pytest.raises(HostError):
        inspect_source(tmp_path, worker=InProcessWorker())
    after = {
        name for name in os.listdir(tempfile.gettempdir()) if name.startswith("sc-imagery-inspect-")
    }
    assert after == before == set()


# --------------------------------------------------------------------------- named outcomes


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def test_each_capability_has_its_own_named_outcome_and_none_is_one_compatible_flag(
    services, store, tmp_path
):
    import base64

    from synapse_imagery.worker import Window

    octets = vector("geo_dms.ntf")
    compressed = with_ic(vector("mono_nsif101.ntf"), "C8")
    service = services(store, worker=InProcessWorker())
    located = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    packed = service.ingest(
        compressed, principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    inspected = inspect_source(compressed, worker=InProcessWorker())
    # Container inventory: the inspect document's structure.
    assert (inspected["valid"], inspected["segments"]["image"]) == (True, 1)
    # Metadata preservation: the whole input once in the product residual, and replay.
    objects = service.catalog.objects(located["record_id"], principal=LOCAL)
    wire = objects[0]["residual"]["data"]["stanag4545"]["wire_b64"]
    assert base64.b64decode(wire) == octets
    replayed = service.replay_original(located["record_id"], tmp_path / "r.ntf", principal=LOCAL)
    assert replayed["relay"] == "unchanged_original_octets" and replayed["authored"] is False
    # CDM translation: one product and one footprint.
    assert [item.get("object_type") for item in objects] == [None, "ANNOTATION"]
    assert len(located["cdm_ids"]) == 2
    # Native samples, and the compressed cell answered separately.
    assert located["images"][0]["pixel_status"] == "native_supported"
    window = service.decode_window(
        located["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL
    )
    assert window.window.values() == (0, 64, 128, 255)
    assert packed["images"] == [
        {"index": 0, "pixel_status": "unsupported", "geometry_status": "absent"}
    ]
    assert (inspected["images"][0]["pixel_status"], inspected["images"][0]["pixel_reason"]) == (
        "unsupported",
        "compression_not_enabled",
    )
    # Geographic footprint.
    assert located["images"][0]["geometry_status"] == "available"
    # New export: its own receipt, labelled experimental.
    recipe = tmp_path / "recipe.json"
    recipe.write_text(
        json.dumps(
            {
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
                    "samples_b64": "AECA/w==",
                },
            }
        )
    )
    exported = service.export_nc(recipe, tmp_path / "e.ntf", principal=LOCAL)
    assert exported["status"] == "experimental"
    previewed = service.preview(located["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    shown = service.catalog.presentation(located["record_id"], principal=LOCAL)
    for document in (located, packed, inspected, replayed, exported, previewed, shown):
        assert not [key for key in _keys(document) if "compatib" in key.lower()]


def test_a_metadata_only_import_says_pixels_and_placement_are_unavailable(services, store):
    octets = with_ic(vector("mono_nsif101.ntf"), "C3")
    service, result = committed(services, store, octets)
    assert result["images"] == [
        {"index": 0, "pixel_status": "unsupported", "geometry_status": "absent"}
    ]
    document = inspect_source(octets, worker=InProcessWorker())
    image_entry = document["images"][0]
    assert (
        image_entry["pixel_status"],
        image_entry["pixel_reason"],
        image_entry["geometry_status"],
    ) == ("unsupported", "compression_not_enabled", "absent")
    for shown in (
        document["presentation"]["images"][0],
        service.catalog.presentation(result["record_id"], principal=LOCAL)["images"][0],
    ):
        assert shown["pixel_message"] == (
            "Image data preserved; this encoding is not supported by this deployment."
        )
        assert shown["geometry_message"] == "No usable geographic footprint."
        assert shown["map"] == "none" and shown["preview"] == "not_available"


def test_text_is_never_displayed_by_the_host(services, store, tmp_path):
    octets = vector("image_and_text.ntf")
    service, result = committed(services, store, octets)
    documents = [
        inspect_source(octets, worker=InProcessWorker()),
        service.catalog.presentation(result["record_id"], principal=LOCAL),
        service.replay_original(result["record_id"], tmp_path / "r.ntf", principal=LOCAL),
        store.read_record("local", result["record_id"], area="records")["presentation"],
    ]
    for document in documents:
        text_out = canonical.serialise(document)
        assert "<script>" not in text_out and "must remain plain text" not in text_out
        assert "SYNTHETIC TEXT" not in text_out
    assert documents[0]["segments"]["text"] == 1
