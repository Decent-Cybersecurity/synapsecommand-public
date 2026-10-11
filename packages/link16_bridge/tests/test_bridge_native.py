"""The native provider boundary (REQ003, REQ005, REQ006, REQ020-022, REQ110, REQ170, REQ180-182;
acceptance rows G02, N01-N06, G03). Nothing native exists; the refusal is the evidence."""
import hashlib
import json
import pathlib

import pytest

from helpers import T0
from synapse_cdm.normative_binding import NormativeBindingBlocked
from synapse_link16_bridge import native
from synapse_link16_bridge.clock import ManualClock
from synapse_link16_bridge.gateway.provider import SyntheticProvider


@pytest.fixture
def provider():
    synthetic = SyntheticProvider(ManualClock(T0))
    yield synthetic
    synthetic.close()


def write_pin(directory: pathlib.Path, *, record_changes=None, definitions_changes=None,
              rows=None) -> dict:
    """A pin record and a conformance matrix written in a temporary directory (synthetic
    content; every digest computed here)."""
    rows = rows if rows is not None else [{column: "synthetic-" + column
                                           for column in native.MATRIX_COLUMNS}]
    matrix = json.dumps(rows).encode("utf-8")
    (directory / native.MATRIX_NAME).write_bytes(matrix)
    record = {field: "synthetic-" + field for field in native.PIN_FIELDS}
    record["document_sha256"] = hashlib.sha256(b"synthetic document").hexdigest()
    record["definitions"] = {name: "synthetic definition" for name in native.DEFINITIONS}
    record["definitions"].update(definitions_changes or {})
    record["files"] = {native.MATRIX_NAME: hashlib.sha256(matrix).hexdigest()}
    record.update(record_changes or {})
    (directory / native.RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")
    return {native.ENV_VAR: str(directory)}


def test_native_activation_without_hook_is_blocked_external_evidence(provider):
    with pytest.raises(NormativeBindingBlocked) as caught:
        native.activate_native(provider, "P", environ={})
    assert (caught.value.status, caught.value.step) == ("BLOCKED_EXTERNAL_EVIDENCE", "hook")
    assert native.ENV_VAR in str(caught.value)


def test_no_provider_object_is_blocked_even_with_a_complete_pin(tmp_path):
    environ = write_pin(tmp_path)
    with pytest.raises(NormativeBindingBlocked) as caught:
        native.activate_native(None, "P", environ=environ)
    assert caught.value.step == "hook"
    with pytest.raises(NormativeBindingBlocked):
        native.activate_native(object(), "P", environ=environ)


def test_no_fallback_to_the_synthetic_provider(tmp_path, provider):
    """The synthetic provider is never put in a native provider's place: with every native
    input missing, activation refuses rather than returning the synthetic one."""
    with pytest.raises(NormativeBindingBlocked):
        native.activate_native(provider, "SYNTHETIC-NO-NATIVE-CODEC",
                               environ={native.ENV_VAR: str(tmp_path / "absent")})


@pytest.mark.parametrize("kwargs, what", [
    ({"definitions_changes": {"quantisation": ""}}, "the pin leaves a REQ021 definition empty"),
    ({"record_changes": {"standard_edition": ""}}, "the pin leaves a REQ020 field empty"),
    ({"record_changes": {"transport_variant": None}}, "the pin leaves a REQ020 field empty"),
    ({"rows": [dict({c: "x" for c in native.MATRIX_COLUMNS}, test_result="SKIP")]},
     "a conformance matrix row has a SKIP outcome"),
    ({"rows": [dict({c: "x" for c in native.MATRIX_COLUMNS}, reviewer=" ")]},
     "a conformance matrix row has a blank mandatory cell"),
    ({"rows": []}, "the conformance matrix has no row"),
])
def test_incomplete_pin_is_native_profile_incomplete(tmp_path, provider, kwargs, what):
    environ = write_pin(tmp_path, **kwargs)
    with pytest.raises(native.NativeProfileIncomplete) as caught:
        native.activate_native(provider, "P", environ=environ)
    assert (caught.value.code, caught.value.what) == ("NATIVE_PROFILE_INCOMPLETE", what)


def test_a_complete_pin_and_a_provider_activate_so_the_gate_is_not_vacuous(tmp_path, provider):
    activation = native.activate_native(provider, "P", environ=write_pin(tmp_path))
    assert activation.native_profile == "P"
    assert activation.record["transport_variant"] == "synthetic-transport_variant"


def test_a_checksum_mismatch_is_blocked(tmp_path, provider):
    environ = write_pin(tmp_path)
    (tmp_path / native.MATRIX_NAME).write_text("[]", encoding="utf-8")
    with pytest.raises(NormativeBindingBlocked) as caught:
        native.activate_native(provider, "P", environ=environ)
    assert caught.value.step == "checksum"


def test_pin_record_keeps_transport_variant_and_edition_separate():
    """REQ006 and REQ020."""
    assert native.PIN_FIELDS == ("document_identifier", "edition", "changes", "publication_date",
                                 "document_sha256", "applicable_clauses", "provider_version",
                                 "transport_variant", "standard_edition", "transport_options",
                                 "j_series_coverage", "test_evidence")
    assert len(native.DEFINITIONS) == 18 and "forwarding_procedures" in native.DEFINITIONS
    assert native.MATRIX_COLUMNS == ("standard", "edition", "clause", "requirement_id",
                                     "decoder_function", "encoder_function", "fixture_ids",
                                     "oracle_identity", "test_result", "limitation", "reviewer",
                                     "review_date")


def test_synthetic_provider_satisfies_the_provider_protocol(provider):
    """REQ110: the seven operations, as a structural protocol."""
    assert isinstance(provider, native.NativeProvider)
    provider.start(None)
    assert provider.capabilities()["profile"] == "sc-link16-gateway/1.0.0"
    assert provider.encode({"b": 1, "a": 2}, None) == b'{"a":2,"b":1}'
    assert provider.send(b"{}") == "SENT"
    assert provider.status("00000000-0000-4000-8000-000000000001") is None
    with pytest.raises(ValueError):
        provider.start({"addresses": []})
    provider.stop()
    assert provider.health_document is not None


def test_native_boundary_is_a_protocol_with_no_implementation():
    """REQ003: no module of this distribution frames, encodes or decodes native traffic."""
    package = pathlib.Path(native.__file__).parent
    names = sorted(p.stem for p in package.rglob("*.py"))
    assert not [n for n in names if any(w in n for w in ("jreap", "codec", "frame", "jseries"))]
    assert native.NativeProvider.__mro__[1].__name__ == "Protocol"


def test_native_status_exits_nonzero(tmp_path, capsys):
    from helpers import config_dict
    from synapse_link16_bridge import cli
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_dict(str(tmp_path / "s.sqlite"))), encoding="utf-8")
    assert cli.main(["native-status", str(path)]) == 3
    printed = json.loads(capsys.readouterr().out)
    assert (printed["status"], printed["detail"]) == ("BLOCKED_EXTERNAL_EVIDENCE", "step hook")


def test_release_stages_are_reported_separately():
    """REQ182: four stages, each on its own; passing one awards no other; no score."""
    assert native.release_stages(True) == {
        "internal_gateway_translation": "IMPLEMENTED",
        "native_codec": "BLOCKED_EXTERNAL_EVIDENCE",
        "interoperability_with_a_named_peer": "NOT_RUN",
        "deployment_in_a_named_authorised_environment": "NOT_CLAIMED"}
    assert native.release_stages(False)["internal_gateway_translation"] == "NOT_READY"


NATIVE_ROWS = [
    ("N01", "split a native frame at every byte boundary", "N01, N03, N07"),
    ("N02", "several native frames in one TCP read", "N01, N02, N03, N07"),
    ("N03", "bad frame length or impossible word combination", "N03, N04, N07"),
    ("N04", "UDP sender mismatch, loss, duplicate, reorder, packing", "N02, N03, N07"),
    ("N05", "unknown legal J-series family kept opaque", "N04, N05, N07"),
    ("N06", "all required word forms and numeric edge codes", "N04, N07"),
    ("G03", "independent peer bidirectional trial", "N08"),
]


@pytest.mark.native
@pytest.mark.parametrize("row, stimulus, gates", NATIVE_ROWS)
def test_native_acceptance_row(row, stimulus, gates):
    pytest.skip(f"BLOCKED_EXTERNAL_EVIDENCE: {row} ({stimulus}) needs native evidence from "
                f"outside this repository; unblocked by gates {gates}")
