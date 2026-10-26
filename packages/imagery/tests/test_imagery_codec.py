"""The codec matrix: every compressed and masked cell disabled, the per-image capability report,
and the adapter's E_CODEC and E_PROFILE answers for every image outside the native NC cell."""

from __future__ import annotations

import os

import pytest
from conftest import LOCAL
from helpers import build_nsif, image, sha, vector, with_ic

from synapse_cdm.adapters.nsif_codec import NsifError
from synapse_imagery.fakes import InProcessWorker
from synapse_imagery.worker import CODEC_MATRIX, ENABLED_CODEC_CELLS, Window, WorkerPool

MONO = vector("mono_nsif101.ntf")
CANDIDATES = ("NM", "C3", "M3", "C8", "M8")
PRESERVATION = ("C1", "M1", "C4", "M4", "C5", "M5")


def test_every_cell_of_the_matrix_is_disabled():
    assert all(not cell.enabled for cell in CODEC_MATRIX)
    assert ENABLED_CODEC_CELLS == ()
    assert [cell.ic for cell in CODEC_MATRIX] == list(CANDIDATES + PRESERVATION)
    assert {cell.family for cell in CODEC_MATRIX if cell.ic in CANDIDATES} == {"candidate"}
    assert {cell.family for cell in CODEC_MATRIX if cell.ic in PRESERVATION} == {
        "preservation_only"
    }
    assert {cell.reason for cell in CODEC_MATRIX} == {"no qualified backend in this release (L-03)"}


def _inspect(worker, tmp_path, octets, index=0):
    path = tmp_path / "source.ntf"
    path.write_bytes(octets)
    fd = os.open(path, os.O_RDONLY)
    try:
        return worker.inspect_codec(fd, index, expected_sha256=sha(octets), byte_count=len(octets))
    finally:
        os.close(fd)


@pytest.mark.parametrize("ic", CANDIDATES + PRESERVATION)
def test_a_compressed_or_masked_image_commits_its_metadata_and_decodes_nothing(
    services, store, tmp_path, ic
):
    octets = with_ic(MONO, ic)
    service = services(store, worker=InProcessWorker())
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "committed"
    assert result["images"][0]["pixel_status"] == "unsupported"
    capability = _inspect(InProcessWorker(), tmp_path, octets)
    masked = ic.startswith("M") or ic == "NM"
    assert (capability.enabled, capability.path, capability.reason, capability.masked) == (
        False,
        "none",
        "compression_not_enabled",
        masked,
    )
    assert (
        capability.cell
        == f"IC={ic};PVTYPE=INT;NBPP=8;ABPP=8;IMODE=B;MASK={'yes' if masked else 'no'}"
    )
    with pytest.raises(NsifError) as caught:
        service.decode_window(result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_CODEC",
        "pixels",
        777,
        "/segments/image[0]/IC",
    )
    with pytest.raises(NsifError) as caught:
        service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_CODEC",
        "pixels",
        777,
        "/segments/image[0]/IC",
    )
    assert store.list_derivatives(result["asset_id"], tenant="local") == []
    assert not (tmp_path / "p.png").exists()
    assert os.listdir(os.path.join(store.root, "staging")) == []


def test_an_unknown_code_is_unsupported_compression(services, store, tmp_path):
    octets = with_ic(MONO, "ZZ")
    capability = _inspect(InProcessWorker(), tmp_path, octets)
    assert (capability.enabled, capability.reason) == (False, "unsupported_compression")
    service = services(store, worker=InProcessWorker())
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    with pytest.raises(NsifError) as caught:
        service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    assert (caught.value.code, caught.value.path) == ("E_CODEC", "/segments/image[0]/IC")


def test_the_native_cell_is_the_one_enabled_path(tmp_path):
    pool = WorkerPool()
    try:
        capability = _inspect(pool, tmp_path, MONO)
    finally:
        pool.shutdown(kill=True)
    assert (capability.enabled, capability.path, capability.reason, capability.masked) == (
        True,
        "native",
        None,
        False,
    )
    assert capability.cell == "IC=NC;PVTYPE=INT;NBPP=8;ABPP=8;IMODE=B;MASK=no"


@pytest.mark.parametrize(
    "options, reason, offset, field",
    [
        ({"pvtype": "R", "nbpp": 32}, "unsupported_sample_type", 753, "PVTYPE"),
        ({"nbpp": 12}, "unsupported_sample_type", 811, "NBPP"),
        ({"imode": "S"}, "unsupported_sample_layout", 794, "IMODE"),
    ],
)
def test_an_nc_image_outside_the_native_cell_is_e_profile(
    services, store, tmp_path, options, reason, offset, field
):
    octets = build_nsif([image(**options)])
    capability = _inspect(InProcessWorker(), tmp_path, octets)
    assert (capability.enabled, capability.reason) == (False, reason)
    service = services(store, worker=InProcessWorker())
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "committed"
    with pytest.raises(NsifError) as caught:
        service.decode_window(result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL)
    assert (caught.value.code, caught.value.offset, caught.value.path) == (
        "E_PROFILE",
        offset,
        f"/segments/image[0]/{field}",
    )
    with pytest.raises(NsifError) as caught:
        service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    assert (caught.value.code, caught.value.offset, caught.value.path) == (
        "E_PROFILE",
        offset,
        f"/segments/image[0]/{field}",
    )
    assert store.list_derivatives(result["asset_id"], tenant="local") == []


def test_inspect_codec_checks_the_image_index_against_its_own_parse(tmp_path):
    with pytest.raises(NsifError) as caught:
        _inspect(InProcessWorker(), tmp_path, MONO, index=1)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_FIELD",
        "pixels",
        "/window/image_index",
    )
