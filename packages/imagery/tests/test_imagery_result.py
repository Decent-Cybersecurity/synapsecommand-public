"""The host result: its eleven keys per state, diagnostic order and the 256 bound, the host codes,
and the validator's schema and semantic checks."""

from __future__ import annotations

import copy
import hashlib
import importlib.resources
import re

import pytest
from conftest import LOCAL
from helpers import build_nsif, image, vector, with_ic

from synapse_cdm.adapters.nsif_codec import DIAGNOSTIC_CODES, ERROR_CODES
from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container
from synapse_imagery.fakes import InProcessWorker
from synapse_imagery.ingest import RetentionPolicy
from synapse_imagery.result import HOST_CODES, ResultContractError, validate_result

KIT_RESULT_SCHEMA_SHA256 = "9b9fa1c7e26e229a765d0fffbc8b1cb2f85bcd301767bc1651e6d0e64e60ef65"
REQUIRED = [
    "schema",
    "record_id",
    "state",
    "sha256",
    "source_bytes",
    "profile",
    "synthetic",
    "asset_id",
    "cdm_ids",
    "images",
    "diagnostics",
]
STATES = {
    "mono_nsif101.ntf": "committed",
    "mono_nsif100.ntf": "committed",
    "mono_nitf210.ntf": "committed",
    "geo_dms.ntf": "committed",
    "unknown_duplicate_tre.ntf": "policy_blocked",
    "mode_B.ntf": "committed",
    "mode_P.ntf": "committed",
    "mode_R.ntf": "committed",
    "mode_S.ntf": "committed",
    "uint16.ntf": "committed",
    "image_and_text.ntf": "committed",
    "header_only.ntf": "rejected",
    "bad_file_length.ntf": "rejected",
    "truncated.ntf": "rejected",
    "trailing.ntf": "rejected",
    "bad_count.ntf": "rejected",
    "unsupported_stype.ntf": "rejected",
}
CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


def run(service, octets):
    return service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)


@pytest.fixture
def service(services, store):
    return services(store, worker=InProcessWorker())


@pytest.mark.parametrize("name", sorted(STATES))
def test_every_kit_vector_gives_a_valid_result_in_its_state(service, name):
    result = run(service, vector(name))
    validate_result(result)
    assert result["state"] == STATES[name]
    assert list(result) == REQUIRED
    assert (result["schema"], result["profile"], result["synthetic"]) == (
        "sc-imagery-result/1",
        "SC4545-CORE-1",
        True,
    )
    for entry in result["diagnostics"]:
        assert CODE.fullmatch(entry["code"])
        assert (
            entry["code"] in HOST_CODES
            or entry["code"] in DIAGNOSTIC_CODES
            or entry["code"] in ERROR_CODES
        )
        assert list(entry) == ["code", "stage", "offset", "path", "message"]


def test_the_image_entries_carry_pixel_and_geometry_status_separately(service):
    assert run(service, vector("geo_dms.ntf"))["images"] == [
        {"index": 0, "pixel_status": "native_supported", "geometry_status": "available"}
    ]
    assert run(service, vector("mono_nsif101.ntf"))["images"][0]["geometry_status"] == "absent"
    compressed = run(service, with_ic(vector("mono_nsif101.ntf"), "C3"))
    assert compressed["state"] == "committed"
    assert compressed["images"] == [
        {"index": 0, "pixel_status": "unsupported", "geometry_status": "absent"}
    ]
    assert [(d["code"], d["stage"], d["offset"], d["path"]) for d in compressed["diagnostics"]] == [
        ("COMPRESSION_NOT_ENABLED", "pixels", 777, "/segments/image[0]/IC")
    ]
    assert run(service, vector("unknown_duplicate_tre.ntf"))["images"] == [
        {"index": 0, "pixel_status": "policy_blocked", "geometry_status": "policy_blocked"}
    ]


def test_a_rejected_result_carries_the_fatal_error_and_the_retention_fact(
    services, store, tmp_path
):
    from synapse_imagery.assets import LocalAssetStore

    fatal = {
        "code": "E_DIGITS",
        "stage": "header",
        "offset": 360,
        "path": "/file_header/NUMI",
        "message": "an octet outside 0x30-0x39",
    }
    kept = services(
        LocalAssetStore(tmp_path / "kept"),
        worker=InProcessWorker(),
        retention=RetentionPolicy(True),
    )
    assert run(kept, vector("bad_count.ntf"))["diagnostics"] == [fatal]
    default = run(services(store, worker=InProcessWorker()), vector("bad_count.ntf"))
    # Offsetless first: the retention fact sorts before a fatal error that has an offset.
    assert default["diagnostics"] == [
        {
            "code": "ORIGINAL_NOT_RETAINED",
            "stage": "storage",
            "offset": None,
            "path": "/asset",
            "message": "rejected octets were not retained under the operator's retention policy",
        },
        fatal,
    ]
    assert (default["cdm_ids"], default["images"], default["asset_id"]) == ([], [], None)


def test_a_blocked_result_names_the_policy_and_its_reason(service):
    result = run(service, vector("unknown_duplicate_tre.ntf"))
    assert result["diagnostics"][0] == {
        "code": "E_POLICY",
        "stage": "security",
        "offset": None,
        "path": "/policy/metadata",
        "message": "publication refused by policy sc-imagery-default-clean-u/1: STATUS_NOT_DECLARED_UNCLASSIFIED",
    }
    assert result["diagnostics"][1]["code"] == "POLICY_ASSESSMENT_INCOMPLETE"
    assert (result["diagnostics"][1]["stage"], result["diagnostics"][1]["path"]) == (
        "security",
        "/security/extensions",
    )


def test_the_host_codes_are_disjoint_from_the_adapters():
    assert HOST_CODES == {
        "POLICY_ASSESSMENT_INCOMPLETE",
        "ORIGINAL_NOT_RETAINED",
        "DIAGNOSTICS_TRUNCATED",
    }
    assert HOST_CODES.isdisjoint(DIAGNOSTIC_CODES)
    assert HOST_CODES.isdisjoint(ERROR_CODES)


def _noisy(count: int, geometry: bool) -> bytes:
    """`count` images that each carry one known diagnostic per kind: an all-space IDATIM, a
    non-printable IID2, an uninterpretable ILOC, a disabled compression code and, with
    `geometry`, UTM corners that are never projected. Distinct display levels keep composition
    silent, and a clean file header adds none."""
    return build_nsif(
        [
            image(
                idatim=" " * 14,
                iid2=b"\xff" * 80,
                iloc=b"XXXXXXXXXX",
                ic="C3",
                idlvl=index + 1,
                data=b"\x00" * 4,
                icords="U" if geometry else " ",
                igeolo="33UXP0000000000" * 4 if geometry else "",
            )
            for index in range(count)
        ]
    )


def _sorted_core(octets: bytes) -> list[dict]:
    found = [
        {"code": d.code, "stage": d.stage, "offset": d.offset, "path": d.path, "message": d.message}
        for d in parse_container(octets, CORE1_LIMITS).diagnostics
    ]
    return sorted(
        found, key=lambda d: (d["offset"] is not None, d["offset"] or 0, d["code"], d["path"])
    )


def test_more_than_256_diagnostics_keep_255_and_name_the_rest(service):
    octets = _noisy(60, geometry=True)
    total = 60 * 5
    every = _sorted_core(octets)
    assert len(every) == total
    result = run(service, octets)
    assert result["state"] == "committed"
    assert len(result["diagnostics"]) == 256
    assert result["diagnostics"][:255] == every[:255]
    assert result["diagnostics"][255] == {
        "code": "DIAGNOSTICS_TRUNCATED",
        "stage": "storage",
        "offset": None,
        "path": "/diagnostics",
        "message": f"{total - 255} further diagnostics omitted",
    }
    assert total - 255 == 45


def test_exactly_256_diagnostics_are_kept_whole(service):
    octets = _noisy(64, geometry=False)
    every = _sorted_core(octets)
    assert len(every) == 64 * 4 == 256
    result = run(service, octets)
    assert result["diagnostics"] == every


# --------------------------------------------------------------------------- the validator


def _committed(service):
    return run(service, vector("geo_dms.ntf"))


def _broken(doc, edit):
    out = copy.deepcopy(doc)
    edit(out)
    return out


def test_the_schema_file_is_the_kits_byte_for_byte():
    data = (
        importlib.resources.files("synapse_imagery")
        .joinpath("contracts", "ingest-result.schema.json")
        .read_bytes()
    )
    assert hashlib.sha256(data).hexdigest() == KIT_RESULT_SCHEMA_SHA256


def test_documents_the_schema_accepts_are_still_refused_by_the_semantic_checks(service):
    committed = _committed(service)
    validate_result(committed)
    cases = {
        "uppercase-record-id": lambda d: d.update(record_id=d["record_id"].upper()),
        "duplicate-indexes": lambda d: d.update(images=d["images"] * 2),
        "float-index": lambda d: d["images"][0].update(index=0.0),
        "float-source-bytes": lambda d: d.update(source_bytes=907.0),
        "three-ids-one-image": lambda d: d.update(
            cdm_ids=d["cdm_ids"] + ["00000000-0000-5000-8000-000000000000"]
        ),
    }
    for label, edit in cases.items():
        with pytest.raises(ResultContractError):
            validate_result(_broken(committed, edit))


def test_the_per_state_rules(service):
    rejected = run(service, vector("bad_count.ntf"))
    blocked = run(service, vector("unknown_duplicate_tre.ntf"))
    second_error = {
        "code": "E_LENGTH",
        "stage": "header",
        "offset": 342,
        "path": "/file_header/FL",
        "message": "m",
    }
    cases = [
        _broken(rejected, lambda d: d.update(diagnostics=[second_error] + d["diagnostics"])),
        _broken(
            rejected,
            lambda d: d.update(
                state="failed",
                diagnostics=[
                    {
                        "code": "E_POLICY",
                        "stage": "security",
                        "offset": None,
                        "path": "/policy/metadata",
                        "message": "m",
                    }
                ],
            ),
        ),
        _broken(blocked, lambda d: d.update(diagnostics=d["diagnostics"][1:])),
        _broken(blocked, lambda d: d["images"][0].update(geometry_status="available")),
        _broken(blocked, lambda d: d.update(sha256=None)),
        _broken(rejected, lambda d: d.update(asset_id="x", sha256=None)),
    ]
    for case in cases:
        with pytest.raises(ResultContractError):
            validate_result(case)


def test_diagnostics_must_be_sorted_and_truncation_comes_last_at_256(service):
    committed = run(service, _noisy(60, geometry=True))
    validate_result(committed)
    unsorted = _broken(committed, lambda d: d.update(diagnostics=d["diagnostics"][:10][::-1]))
    with pytest.raises(ResultContractError) as caught:
        validate_result(unsorted)
    assert "diagnostic_order" in str(caught.value)
    early = _broken(
        committed,
        lambda d: d.update(
            diagnostics=d["diagnostics"][:3] + [d["diagnostics"][255]] + d["diagnostics"][3:6]
        ),
    )
    with pytest.raises(ResultContractError):
        validate_result(early)


def test_the_schema_refuses_what_it_can_see(service):
    committed = _committed(service)
    for edit in (
        lambda d: d.update(extra=1),
        lambda d: d.update(sha256=None),
        lambda d: d.update(cdm_ids=[]),
        lambda d: d.update(record_id="not-a-uuid"),
        lambda d: d["diagnostics"].append(
            {"code": "lower", "stage": "cdm", "offset": None, "path": "/", "message": ""}
        ),
        lambda d: d.update(source_bytes=True),
    ):
        with pytest.raises(ResultContractError) as caught:
            validate_result(_broken(committed, edit))
        assert str(caught.value) == "result contract violated: schema"
