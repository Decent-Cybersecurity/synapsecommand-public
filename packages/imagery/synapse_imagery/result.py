"""The host result: its errors, its diagnostic vocabulary, its builder and its validator.

Every refusal the host raises is a `HostError` in the adapter's error form,
`CODE @byte OFFSET PATH: message`, with the same seventeen codes and ten stages, so a log line or a
result diagnostic reads the same whichever layer refused. Messages are fixed texts: they never
carry a source value, a label value, a coordinate or a title.

The result document is `contracts/ingest-result.schema.json`, a byte copy of the engineering
kit's schema. The schema validates structure only; `validate_result` adds the cross-field checks
the schema cannot express (canonical UUID text, integer types, the per-state rules, image index
order, diagnostic order and the object-count bound), and every result the host returns passes it.
"""

from __future__ import annotations

import importlib.resources
import json
import uuid

import jsonschema

from synapse_cdm.adapters.nsif_codec import DIAGNOSTIC_CODES, ERROR_CODES, STAGES, render

PROFILE = "SC4545-CORE-1"
RESULT_SCHEMA_ID = "sc-imagery-result/1"

#: The ten codes the adapter's parser, twin decoder, window decoder and translator raise. A worker
#: answer carrying one of them (outside the `/request` and `/worker` paths) is a refusal of the
#: octets themselves; every other code names a host outcome.
CORE_CODES = frozenset(
    (
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
    )
)

#: The codes a `failed` result may carry, one of them, alone.
FAILED_CODES = frozenset(("E_IO", "E_INTERNAL", "E_TIMEOUT", "E_BUSY", "E_INTEGRITY", "E_LIMIT"))

#: The host's own non-fatal codes. Disjoint from the adapter's registry, and never added to it:
#: the host's vocabulary stays out of synapse-cdm.
HOST_CODES = frozenset(
    ("POLICY_ASSESSMENT_INCOMPLETE", "ORIGINAL_NOT_RETAINED", "DIAGNOSTICS_TRUNCATED")
)

#: The artefact values a policy decides independently (the `Artefact` enum of `policy.py` holds
#: the same seven; this module cannot import it, because policy imports this one).
_ARTEFACTS = ("metadata", "original", "pixels", "thumbnail", "tile", "text", "export")

DIAGNOSTIC_BOUND = 256


class HostError(Exception):
    """A coded refusal raised by the host, in the adapter's error form."""

    def __init__(self, code: str, stage: str, offset: int | None, path: str, message: str) -> None:
        if type(code) is not str or code not in ERROR_CODES:
            raise TypeError("code must be one of the section 19 codes")
        if type(stage) is not str or stage not in STAGES:
            raise TypeError("stage must be one of the ten result stages")
        if offset is not None and (type(offset) is not int or offset < 0):
            raise TypeError("offset must be None or an int >= 0")
        if type(path) is not str or not path.startswith("/"):
            raise TypeError("path must be a str starting with '/'")
        if type(message) is not str:
            raise TypeError("message must be a str")
        super().__init__(render(code, offset, path, message))
        self.code = code
        self.stage = stage
        self.offset = offset
        self.path = path
        self.message = message

    def __reduce__(self):
        return (HostError, (self.code, self.stage, self.offset, self.path, self.message))


class PolicyDenied(HostError):
    """A policy refusal of one artefact: always E_POLICY, stage security, no offset."""

    def __init__(self, artefact: object, message: str = "refused by policy") -> None:
        value = getattr(artefact, "value", artefact)
        if type(value) is not str or value not in _ARTEFACTS:
            raise TypeError("artefact must be one of the seven policy artefacts")
        super().__init__("E_POLICY", "security", None, f"/policy/{value}", message)
        self.artefact = value

    def __reduce__(self):
        return (PolicyDenied, (self.artefact, self.message))


class ResultContractError(ValueError):
    """A result document that breaks the schema or a semantic rule; the message names the rules
    that failed and never a value of the document."""


# --------------------------------------------------------------------------- diagnostics


def diagnostic(code: str, stage: str, offset: int | None, path: str, message: str) -> dict:
    return {"code": code, "stage": stage, "offset": offset, "path": path, "message": message}


def from_error(error: Exception) -> dict:
    """The diagnostic of one refusal: an adapter `NsifError` or a `HostError`."""
    message = getattr(error, "explanation", None)
    if message is None:
        message = error.message
    return diagnostic(error.code, error.stage, error.offset, error.path, message)


def policy_refused(policy_id: str, policy_version: str, reason: str) -> dict:
    return diagnostic(
        "E_POLICY",
        "security",
        None,
        "/policy/metadata",
        f"publication refused by policy {policy_id}/{policy_version}: {reason}",
    )


def assessment_incomplete(count: int, registry_version: str) -> dict:
    return diagnostic(
        "POLICY_ASSESSMENT_INCOMPLETE",
        "security",
        None,
        "/security/extensions",
        f"{count} extension record(s) not identified as security-neutral by registry "
        f"{registry_version}",
    )


def original_not_retained() -> dict:
    return diagnostic(
        "ORIGINAL_NOT_RETAINED",
        "storage",
        None,
        "/asset",
        "rejected octets were not retained under the operator's retention policy",
    )


def sort_key(entry: dict) -> tuple:
    """The adapter's diagnostic order: offsetless first, then offset, code and path."""
    offset = entry["offset"]
    return (offset is not None, offset or 0, entry["code"], entry["path"])


def bounded(entries: list[dict]) -> list[dict]:
    """Sorted, then cut to 256: the first 255 and one DIAGNOSTICS_TRUNCATED naming the rest."""
    ordered = sorted(entries, key=sort_key)
    if len(ordered) <= DIAGNOSTIC_BOUND:
        return ordered
    omitted = len(ordered) - (DIAGNOSTIC_BOUND - 1)
    return ordered[: DIAGNOSTIC_BOUND - 1] + [
        diagnostic(
            "DIAGNOSTICS_TRUNCATED",
            "storage",
            None,
            "/diagnostics",
            f"{omitted} further diagnostics omitted",
        )
    ]


# --------------------------------------------------------------------------- the document


def build_result(
    state: str,
    *,
    record_id: str,
    sha256: str | None,
    source_bytes: int,
    synthetic: bool,
    asset_id: str | None,
    cdm_ids: list[str],
    images: list[dict],
    diagnostics: list[dict],
) -> dict:
    """One result document, its eleven keys in the schema's order, diagnostics sorted and
    bounded. The caller validates it before it leaves the host."""
    return {
        "schema": RESULT_SCHEMA_ID,
        "record_id": record_id,
        "state": state,
        "sha256": sha256,
        "source_bytes": source_bytes,
        "profile": PROFILE,
        "synthetic": synthetic,
        "asset_id": asset_id,
        "cdm_ids": list(cdm_ids),
        "images": [dict(image) for image in images],
        "diagnostics": bounded(diagnostics),
    }


_RESULT_KEYS = (
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
)


def ordered(doc: dict) -> dict:
    """A result read back from a record (whose canonical JSON sorts keys) in the schema's key
    order again; nothing but the order changes."""
    out = {key: doc[key] for key in _RESULT_KEYS}
    out["cdm_ids"] = list(doc["cdm_ids"])
    out["images"] = [
        {key: image[key] for key in ("index", "pixel_status", "geometry_status")}
        for image in doc["images"]
    ]
    out["diagnostics"] = [
        diagnostic(entry["code"], entry["stage"], entry["offset"], entry["path"], entry["message"])
        for entry in doc["diagnostics"]
    ]
    return out


def _load_schema() -> dict:
    text = (
        importlib.resources.files("synapse_imagery")
        .joinpath("contracts", "ingest-result.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


SCHEMA = _load_schema()
_VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _semantic_failures(doc: dict) -> list[str]:
    failed = []
    images = doc["images"]
    entries = doc["diagnostics"]
    if (
        type(doc["source_bytes"]) is not int
        or type(doc["synthetic"]) is not bool
        or any(type(image["index"]) is not int for image in images)
        or any(
            entry["offset"] is not None and type(entry["offset"]) is not int for entry in entries
        )
    ):
        failed.append("integer_types")
    if not _canonical_uuid(doc["record_id"]) or not all(_canonical_uuid(v) for v in doc["cdm_ids"]):
        failed.append("canonical_uuid")
    state = doc["state"]
    codes = [entry["code"] for entry in entries]
    fatal = [code for code in codes if code.startswith("E_")]
    rule = True
    if state == "committed":
        rule = (
            doc["sha256"] is not None
            and doc["asset_id"] is not None
            and len(doc["cdm_ids"]) >= 1
            and all(image["pixel_status"] != "policy_blocked" for image in images)
            and all(image["geometry_status"] != "policy_blocked" for image in images)
        )
    elif state == "policy_blocked":
        rule = (
            doc["sha256"] is not None
            and doc["asset_id"] is not None
            and doc["cdm_ids"] == []
            and all(
                image["pixel_status"] == "policy_blocked"
                and image["geometry_status"] == "policy_blocked"
                for image in images
            )
            and "E_POLICY" in codes
        )
    elif state == "rejected":
        others = [code for code in codes if not code.startswith("E_")]
        rule = (
            doc["cdm_ids"] == []
            and images == []
            and len(fatal) == 1
            and len(others) <= 1
            and all(code == "ORIGINAL_NOT_RETAINED" for code in others)
        )
    elif state == "failed":
        rule = (
            doc["asset_id"] is None
            and doc["cdm_ids"] == []
            and images == []
            and len(codes) == 1
            and codes[0] in FAILED_CODES
        )
    if doc["sha256"] is None and (
        state not in ("rejected", "failed") or doc["asset_id"] is not None
    ):
        rule = False
    if not rule:
        failed.append("state_rules")
    if [image["index"] for image in images] != list(range(len(images))):
        failed.append("image_indexes")
    body = entries
    if body and body[-1]["code"] == "DIAGNOSTICS_TRUNCATED" and len(body) == DIAGNOSTIC_BOUND:
        body = body[:-1]
    if "DIAGNOSTICS_TRUNCATED" in [entry["code"] for entry in body] or body != sorted(
        body, key=sort_key
    ):
        failed.append("diagnostic_order")
    if any(code not in ERROR_CODES for code in fatal):
        failed.append("error_codes")
    if len(doc["cdm_ids"]) > 1 + len(images):
        failed.append("cdm_id_bound")
    return failed


def validate_result(doc: object) -> None:
    """Raise `ResultContractError` unless `doc` passes the schema (with its format checker) and
    every semantic rule; the message names the rules that failed."""
    if any(True for _ in _VALIDATOR.iter_errors(doc)):
        raise ResultContractError("result contract violated: schema")
    failed = _semantic_failures(doc)
    if failed:
        raise ResultContractError("result contract violated: " + ", ".join(failed))


def known_code(code: str) -> bool:
    """A code a result may carry: a section 19 code, the adapter's registry or the host's own."""
    return code in ERROR_CODES or code in DIAGNOSTIC_CODES or code in HOST_CODES
