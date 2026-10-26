"""Replay of the original octets: the policy asked again, the digest and length recomputed, an
atomic write, exactly the stored octets, a corrupt object refused and marked, every mutation
refused, and a receipt that tells the receiver what it is getting."""

from __future__ import annotations

import os
import pathlib
import uuid

import pytest
from conftest import LOCAL
from helpers import build_nsif, graphic, image, sha, vector, with_ic

from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.ingest import tenant_directory
from synapse_imagery.policy import Artefact, Principal
from synapse_imagery.result import HostError

GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
NOTICE = (
    "Original octets relayed unchanged: not a newly authored NSIF file, not a CDM translation, "
    "and no unrecognised extension was interpreted."
)
ALLOW_ALL = {artefact: True for artefact in Artefact}


def committed(services, store, octets, policy=None, principal=LOCAL):
    service = services(store, worker=InProcessWorker(), policy=policy)
    result = service.ingest(
        octets, principal=principal, dataset_namespace="default", synthetic=True
    )
    assert result["state"] == "committed", result["diagnostics"]
    return service, result


def original_path(store, result, tenant="local") -> pathlib.Path:
    return (
        pathlib.Path(store.root, "tenants", tenant_directory(tenant), "originals")
        / result["asset_id"]
    )


def no_part(directory) -> bool:
    return not [name for name in os.listdir(directory) if name.endswith(".part")]


def test_a_replay_writes_exactly_the_original_octets(services, store, tmp_path):
    octets = vector("geo_dms.ntf")
    service, result = committed(services, store, octets)
    destination = tmp_path / "out.ntf"
    receipt = service.replay_original(result["record_id"], destination, principal=LOCAL)
    assert destination.read_bytes() == octets
    assert receipt == {
        "schema": "sc-imagery-replay/1",
        "record_id": result["record_id"],
        "asset_id": result["asset_id"],
        "sha256": sha(octets),
        "bytes": 907,
        "wire_signature": "NSIF01.01",
        "relay": "unchanged_original_octets",
        "authored": False,
        "retained_unsupported": [],
        "notice": NOTICE,
    }
    assert os.stat(destination).st_mode & 0o777 == 0o600
    assert no_part(tmp_path)


@pytest.mark.parametrize(
    "octets, signature",
    [
        (vector("mono_nitf210.ntf"), "NITF02.10"),
        (vector("mono_nsif100.ntf"), "NSIF01.00"),
    ],
)
def test_the_receipt_names_the_actual_wire_signature(services, store, tmp_path, octets, signature):
    service, result = committed(services, store, octets)
    receipt = service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert receipt["wire_signature"] == signature
    assert (tmp_path / "o.ntf").read_bytes() == octets


def test_retained_extensions_are_named_as_not_interpreted(services, store, tmp_path):
    octets = vector("unknown_duplicate_tre.ntf")
    service, result = committed(services, store, octets, policy=FakePolicy(ALLOW_ALL))
    receipt = service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert receipt["retained_unsupported"] == ["tre:2:not_interpreted"]
    assert (tmp_path / "o.ntf").read_bytes() == octets


def test_retained_graphics_are_named_as_not_rendered(services, store, tmp_path):
    octets = build_nsif([image(icords="G", igeolo=GEO)], graphics=[graphic()])
    service, result = committed(services, store, octets)
    receipt = service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert receipt["retained_unsupported"] == ["graphic:1:not_rendered"]


def test_unusable_pixels_footprints_and_composition_are_named_in_their_order(
    services, store, tmp_path
):
    bad_corner = "486000N" + GEO[7:]
    octets = build_nsif(
        [image(ic="C3"), image(icords="G", igeolo=bad_corner, idlvl=2)],
        graphics=[graphic(sdlvl=2, salvl=1)],
    )
    service, result = committed(services, store, octets)
    receipt = service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert receipt["retained_unsupported"] == [
        "graphic:1:not_rendered",
        "image[0]:pixels:compression_not_enabled",
        "image[1]:geometry:invalid",
        "composition:unavailable",
    ]
    assert (tmp_path / "o.ntf").read_bytes() == octets


def test_a_compressed_image_is_relayed_and_named(services, store, tmp_path):
    octets = with_ic(vector("mono_nsif101.ntf"), "C3")
    service, result = committed(services, store, octets)
    receipt = service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert receipt["retained_unsupported"] == ["image[0]:pixels:compression_not_enabled"]
    assert (tmp_path / "o.ntf").read_bytes() == octets


def test_a_corrupted_original_is_refused_marked_and_never_relayed(services, store, tmp_path):
    octets = vector("geo_dms.ntf")
    service, result = committed(services, store, octets)
    path = original_path(store, result)
    os.chmod(path, 0o600)
    damaged = bytearray(path.read_bytes())
    damaged[500] ^= 0x01
    path.write_bytes(bytes(damaged))
    os.chmod(path, 0o400)
    destination = tmp_path / "out.ntf"
    with pytest.raises(HostError) as caught:
        service.replay_original(result["record_id"], destination, principal=LOCAL)
    error = caught.value
    assert (error.code, error.stage, error.offset, error.path, error.message) == (
        "E_INTEGRITY",
        "storage",
        None,
        "/asset",
        "stored original differs from its recorded digest or length",
    )
    assert not destination.exists() and no_part(tmp_path)
    marker = pathlib.Path(store.root, "tenants", tenant_directory("local"), "integrity-failed")
    assert (marker / result["asset_id"]).is_file()
    # The stored object stays in place for investigation, and the next replay is refused at the
    # open, before a single octet is read.
    assert path.read_bytes() == bytes(damaged)
    with pytest.raises(HostError) as again:
        service.replay_original(result["record_id"], destination, principal=LOCAL)
    assert (again.value.code, again.value.message) == (
        "E_INTEGRITY",
        "this original failed its integrity check",
    )
    assert not destination.exists()


def test_an_existing_destination_is_kept_unless_replace_is_asked(services, store, tmp_path):
    octets = vector("mono_nsif101.ntf")
    service, result = committed(services, store, octets)
    destination = tmp_path / "out.ntf"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        service.replay_original(result["record_id"], destination, principal=LOCAL)
    assert destination.read_bytes() == b"keep"
    service.replay_original(result["record_id"], destination, principal=LOCAL, replace=True)
    assert destination.read_bytes() == octets
    assert no_part(tmp_path)


@pytest.mark.parametrize("mutations", [("crop",), ("labels",), ["pixels"], ("metadata",)])
def test_every_mutation_is_refused(services, store, tmp_path, mutations):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    with pytest.raises(HostError) as caught:
        service.replay_original(
            result["record_id"], tmp_path / "o.ntf", principal=LOCAL, mutations=mutations
        )
    error = caught.value
    assert (error.code, error.stage, error.path, error.message) == (
        "E_POLICY",
        "export",
        "/replay/mutations",
        "replay relays the unchanged original; any change needs a new authored product and a "
        "fresh policy review",
    )
    assert not (tmp_path / "o.ntf").exists()


def test_an_unknown_record_is_answered_alike_whatever_the_reason(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    answers = set()
    for principal, record_id in (
        (Principal("t2", "a"), result["record_id"]),
        (LOCAL, str(uuid.uuid4())),
        (LOCAL, result["record_id"].upper()),
        (LOCAL, "../../x"),
        (LOCAL, None),
    ):
        with pytest.raises(HostError) as caught:
            service.replay_original(record_id, tmp_path / "o.ntf", principal=principal)
        answers.add(str(caught.value))
    assert answers == {
        "E_FIELD @byte - /record_id: no committed record with this id for this principal"
    }


def test_a_rejected_record_is_not_a_record_to_replay(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    result = service.ingest(
        vector("bad_count.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    assert result["state"] == "rejected"
    with pytest.raises(HostError) as caught:
        service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_FIELD", "/record_id")


def test_a_quarantined_original_is_a_policy_refusal(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    blocked = service.ingest(
        vector("unknown_duplicate_tre.ntf"),
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
    )
    assert blocked["state"] == "policy_blocked"
    with pytest.raises(HostError) as caught:
        service.replay_original(blocked["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/original")
    assert not (tmp_path / "o.ntf").exists()


def test_a_policy_that_denies_the_original_refuses_the_replay(services, store, tmp_path):
    service, result = committed(services, store, vector("mono_nsif101.ntf"))
    denying = services(
        store,
        worker=InProcessWorker(),
        policy=FakePolicy({Artefact.METADATA: True, Artefact.THUMBNAIL: True}),
    )
    with pytest.raises(HostError) as caught:
        denying.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_POLICY",
        "security",
        "/policy/original",
    )
    assert not (tmp_path / "o.ntf").exists()


def test_a_revocation_between_write_and_link_delivers_nothing(services, store, tmp_path):
    def revoke(point):
        if point == "replay_part_written":
            service._authority.advance_epoch()

    service = services(store, worker=InProcessWorker(), _fault=revoke)
    result = service.ingest(
        vector("mono_nsif101.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    with pytest.raises(HostError) as caught:
        service.replay_original(result["record_id"], tmp_path / "o.ntf", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/original")
    assert not (tmp_path / "o.ntf").exists() and no_part(tmp_path)


def test_an_entry_that_appears_before_the_link_is_never_overwritten(services, store, tmp_path):
    # The destination is absent when the replay checks it and appears after the temporary file
    # is written, just before it is linked into place: the link refuses, the newcomer is kept.
    destination = tmp_path / "o.ntf"

    def appear(point):
        if point == "replay_part_written":
            destination.write_bytes(b"newcomer")

    service = services(store, worker=InProcessWorker(), _fault=appear)
    result = service.ingest(
        vector("mono_nsif101.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    with pytest.raises(FileExistsError):
        service.replay_original(result["record_id"], destination, principal=LOCAL)
    assert destination.read_bytes() == b"newcomer"
    assert no_part(tmp_path)


def test_replay_is_not_the_adapters_egress():
    with pytest.raises(NotImplementedError):
        Stanag4545Adapter().from_cdm([])
