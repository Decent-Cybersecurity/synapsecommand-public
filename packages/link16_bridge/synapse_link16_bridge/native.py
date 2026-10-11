"""The native provider boundary: a protocol, a pin record, and an activation that refuses.

Native JREAP C and Link 16 are neither implemented nor claimed here (REQ003, REQ022, REQ180-182).
This module defines what a native provider would have to be and what evidence must pin it, and
refuses to activate one until that evidence exists:

- `NativeProvider` is the REQ110 operations as a Python protocol: `capabilities()`,
  `start(peer_profile)`, `receive()`, `encode(report, destination_context)`, `send(encoded)`,
  `status(request_id)`, `stop()`, with typed results carrying the exact native profile and
  evidence references. A provider is an object the deployer passes in; the bridge never imports a
  module named in configuration.
- `PIN_FIELDS` is REQ020's pin record, with the transport variant and the standard edition as two
  fields (REQ006); `DEFINITIONS` is REQ021's list of verified native definitions;
  `MATRIX_COLUMNS` is REQ170's conformance matrix.
- `activate_native` resolves the pin through `synapse_cdm.normative_binding.resolve` from the
  directory named by `SYNAPSE_LINK16_NATIVE_PROFILE_DIR`: with no provider object, no variable, no
  directory or no record it raises `NormativeBindingBlocked` (status `BLOCKED_EXTERNAL_EVIDENCE`);
  with a record that leaves a REQ020 field or a REQ021 definition empty, or a matrix with a blank
  mandatory cell or a `SKIP` outcome, it raises `NativeProfileIncomplete`
  (`NATIVE_PROFILE_INCOMPLETE`). There is no fallback: the synthetic provider is never put in a
  native provider's place.

The unblock procedure is the specification's gates N01 to N09 (`release_stages` and the
requirement matrix name them); internal JSON tests can never fill a native matrix cell.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
from typing import Any, Mapping, Protocol, runtime_checkable

from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked, resolve

ENV_VAR = "SYNAPSE_LINK16_NATIVE_PROFILE_DIR"
RECORD_NAME = "native_profile_pin.json"
MATRIX_NAME = "conformance_matrix.json"
INCOMPLETE = "NATIVE_PROFILE_INCOMPLETE"

#: REQ020, with REQ006's two distinct fields.
PIN_FIELDS = ("document_identifier", "edition", "changes", "publication_date", "document_sha256",
              "applicable_clauses", "provider_version", "transport_variant", "standard_edition",
              "transport_options", "j_series_coverage", "test_evidence")
#: REQ021.
DEFINITIONS = ("frame_headers", "field_widths_endianness", "frame_length_interpretation",
               "valid_pdu_types", "management_messages", "sequence_spaces_rollover",
               "time_representation", "session_state", "retransmission", "packet_packing",
               "word_ordering", "legal_padding", "initial_extension_continuation_words",
               "conditional_fields", "quantisation", "sentinel_codes", "identity_tables",
               "forwarding_procedures")
#: REQ170.
MATRIX_COLUMNS = ("standard", "edition", "clause", "requirement_id", "decoder_function",
                  "encoder_function", "fixture_ids", "oracle_identity", "test_result",
                  "limitation", "reviewer", "review_date")
#: The gates that unblock the native rows (SPEC section 18).
GATES = ("N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09")
PROCEDURE = tuple((step, what) for step, what in (
    ("hook", f"set {ENV_VAR} to the directory holding the authorised native profile record"),
    ("directory", "the directory exists and is readable"),
    ("record", f"{RECORD_NAME} names every REQ020 field and every REQ021 definition"),
    ("files", f"{MATRIX_NAME} sits beside the record with its SHA-256 in the record"),
    ("checksum", "every file hashes to the digest the record states"),
    ("validator", "every matrix row has every REQ170 column and no SKIP outcome"),
    ("validate", "independent byte vectors and a witnessed peer test (gates N07, N08)"),
))


class NativeProfileIncomplete(ValueError):
    """The pin is present and incomplete (REQ022)."""

    code = INCOMPLETE

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"{INCOMPLETE}: {what}")


@dataclasses.dataclass(frozen=True)
class DecodedMessage:
    native_profile: str
    family: str
    payload: Any
    evidence_refs: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ManagementEvent:
    native_profile: str
    event: str
    evidence_refs: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class TypedNativeError:
    native_profile: str
    code: str
    evidence_refs: tuple[str, ...]


@runtime_checkable
class NativeProvider(Protocol):
    def capabilities(self) -> Any: ...

    def start(self, peer_profile: Any) -> None: ...

    def receive(self) -> Any: ...

    def encode(self, report: dict, destination_context: Any) -> bytes: ...

    def send(self, encoded: bytes) -> Any: ...

    def status(self, request_id: str) -> Any: ...

    def stop(self) -> None: ...


@dataclasses.dataclass(frozen=True)
class NativeActivation:
    native_profile: str
    record: dict


def _matrix_validator(path: pathlib.Path) -> list:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError, OSError):
        raise NativeProfileIncomplete("the conformance matrix is not a JSON list") from None
    if type(rows) is not list or not rows:
        raise NativeProfileIncomplete("the conformance matrix has no row")
    for row in rows:
        if type(row) is not dict or any(type(row.get(c)) is not str or not row.get(c).strip()
                                        for c in MATRIX_COLUMNS):
            raise NativeProfileIncomplete("a conformance matrix row has a blank mandatory cell")
        if row["test_result"].strip().upper() == "SKIP":
            raise NativeProfileIncomplete("a conformance matrix row has a SKIP outcome")
    return rows


def activate_native(provider: Any, native_profile: str,
                    environ: Mapping[str, str] | None = None) -> NativeActivation:
    """Activate a native provider, or refuse. Never falls back."""
    if provider is None:
        raise NormativeBindingBlocked("hook", "no native provider object is configured",
                                      PROCEDURE)
    if not isinstance(provider, NativeProvider):
        raise NormativeBindingBlocked("hook", "the provider does not offer the REQ110 operations",
                                      PROCEDURE)
    resource = resolve(env_var=ENV_VAR, record_name=RECORD_NAME, files=(MATRIX_NAME,),
                       fields=("files",), environ=os.environ if environ is None else environ,
                       validator_factory=_matrix_validator, procedure=PROCEDURE)
    record = resource.record
    empty = [field for field in PIN_FIELDS if not record.get(field)]
    if empty:
        raise NativeProfileIncomplete("the pin leaves a REQ020 field empty")
    definitions = record.get("definitions")
    if type(definitions) is not dict or any(not definitions.get(d) for d in DEFINITIONS):
        raise NativeProfileIncomplete("the pin leaves a REQ021 definition empty")
    return NativeActivation(native_profile, record)


def native_status(provider: Any = None, native_profile: str = "",
                  environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(status, what) for the CLI: BLOCKED_EXTERNAL_EVIDENCE, NATIVE_PROFILE_INCOMPLETE or
    ACTIVE."""
    try:
        activate_native(provider, native_profile, environ)
    except NormativeBindingBlocked as blocked:
        return BLOCKED_STATUS, f"step {blocked.step}"
    except NativeProfileIncomplete as incomplete:
        return INCOMPLETE, incomplete.what
    return "ACTIVE", "native provider activated"


def release_stages(required_families_ready: bool) -> dict[str, str]:
    """REQ182's four release stages, each reported on its own; passing one awards no other."""
    return {
        "internal_gateway_translation": "IMPLEMENTED" if required_families_ready
        else "NOT_READY",
        "native_codec": BLOCKED_STATUS,
        "interoperability_with_a_named_peer": "NOT_RUN",
        "deployment_in_a_named_authorised_environment": "NOT_CLAIMED",
    }
