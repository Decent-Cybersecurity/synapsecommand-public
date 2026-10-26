"""`run.json`, the manifest of a run directory (SPEC:168, OPS-10 as corrected), for the command
line (round R6).

WHAT IT SAYS
------------
A run directory holds the capture and what was made of it; `run.json` says what they are, so
that the four files stay together as evidence (SPEC:166): the profile and the versions of the two
packages, the build's source commit (null until a build stamps one: OPS-10 forbids inventing it),
the session, the SHA-256 of the configuration's canonical bytes, the FOM module digests and the
whole pin map the header recorded, the capture file with its size, digest, status and how far
it was verified, each output file with its size, digest and record count, the records by kind,
the snapshots suppressed by each reason, the diagnostics by code, whether the capture is complete,
the evidence statuses and the audit times.

Completion (SPEC:158): live records carry `capture_complete` null, because completion is not known
while they are written; consumers read it from `run.json` after live closure. So `capture_complete`
here is true when the capture's footer is COMPLETE and false for anything else, in a live run
directory as in a replay one (CR-R6-F8; a replay's records carry the same value).

Evidence (OPS-10, OPS-01, D-14): `offline_replay` is PASS only for a replay of a capture verified
COMPLETE from its first byte to its last, PREFIX_ONLY for any prefix replay (never PASS, R17),
and NOT_RUN for a live session; `external_customer_interoperability` is NOT_TESTED, always: no
witnessed report exists, and nothing here may say otherwise.

Audit times are the only clock values, and only a live session has them: a replay's `audit`
holds two nulls, so that the whole replay directory, `run.json` included, is byte-identical
across repeated replays by one build on one interpreter (OPS-10). The document is canonical JSON
(sorted keys, compact, ASCII) and one LF, and it is held to `local_schemas/run.schema.json` before
it is handed out: a document that fails its own schema is a defect here (`RunFileDefect`), never
written.

This module reads no file, clock or environment (D-08): the caller passes the times and the
installed version of synapse-cdm.
"""

from __future__ import annotations

from synapse_hla import _fom, _schema, _utc, canonical, capture, projector, reducer

SCHEMA = "run.schema.json"
RUN_VERSION = 1
#: OPS-10 (3): the build stamp, written by a release build (round R8); a development build has
#: none, and the manifest says null rather than a value nobody built.
SOURCE_COMMIT = None

OBSERVE = "observe"
REPLAY = "replay"
#: The three other files of a run directory, by the names `replay` and `_writer` give them.
CAPTURE = "capture.jsonl"
OBSERVATIONS = "observations.jsonl"
DIAGNOSTICS = "diagnostics.jsonl"

PASS = "PASS"
PREFIX_ONLY = "PREFIX_ONLY"
FAIL = "FAIL"
NOT_RUN = "NOT_RUN"
#: OPS-01, R48: the one spelling, and its only value until a witnessed report exists.
NOT_TESTED = "NOT_TESTED"


class RunFileDefect(RuntimeError):
    """The manifest this module built fails its own schema: a defect here, never a data fault."""


def _outputs(summary: dict) -> list[dict]:
    files = summary["files"]
    records = sum(summary["records"].values())
    diagnostics = summary["records"][reducer.DIAGNOSTIC]
    return [{"file": name, "bytes": files[name]["bytes"], "sha256": files[name]["sha256"],
             "records": count}
            for name, count in ((OBSERVATIONS, records), (DIAGNOSTICS, diagnostics))]


def _capture_block(summary: dict, *, status: str, reason_code, last_seq: int,
                   verification) -> dict:
    return {"file": CAPTURE, "bytes": summary["files"][CAPTURE]["bytes"],
            "sha256": summary["files"][CAPTURE]["sha256"], "status": status,
            "reason_code": reason_code, "last_seq": last_seq, "frames": summary["frames"],
            "verification": verification}


def _document(command: str, summary: dict, config_document, pins: dict, *, capture_block: dict,
              capture_complete, offline_replay: str, session, audit: dict,
              synapse_cdm_version: str | None) -> dict:
    return {
        "run_version": RUN_VERSION,
        "command": command,
        "profile": capture.PROFILE,
        "adapter_version": capture.ADAPTER_VERSION,
        "source_commit": SOURCE_COMMIT,
        "package_versions": {"synapse_hla": capture.ADAPTER_VERSION,
                             "synapse_cdm": synapse_cdm_version},
        "session_id": config_document["session_id"],
        "config_sha256": canonical.sha256_hex(canonical.canonical_bytes(config_document)),
        "fom_sha256": {name: pins[name] for name in _fom.FOM_MODULES},
        "pins": dict(pins),
        "capture": capture_block,
        "outputs": _outputs(summary),
        "record_counts": {kind: summary["records"][kind] for kind in reducer.KINDS},
        "capture_complete": capture_complete,
        "suppression_counts": {reason: summary["suppressions"][reason]
                               for reason in projector.REASONS},
        "error_counts": dict(summary["errors"]),
        "warning_counts": dict(summary["warnings"]),
        "session": session,
        "evidence": {"offline_replay": offline_replay,
                     "external_customer_interoperability": NOT_TESTED},
        "audit": audit,
    }


def _finished(document: dict) -> bytes:
    validator = _schema.checked_validator(SCHEMA)
    error = next(iter(validator.iter_errors(document)), None)
    if error is not None:
        raise RunFileDefect(f"run.json fails {SCHEMA} ({error.validator})")
    return canonical.canonical_bytes(document) + b"\n"


def replay_run(summary: dict, header: dict, *, synapse_cdm_version: str | None) -> bytes:
    """The `run.json` of a replay directory, from `replay`'s summary (CR-L08: its verification
    says how far the capture was verified) and the recorded header. No clock is read."""
    verification = summary["verification"]
    footer = verification["footer"]
    complete = summary["status"] == capture.COMPLETE
    capture_block = _capture_block(
        summary, status=summary["status"],
        reason_code=None if footer is None else footer["reason_code"],
        last_seq=summary["verified_seq"], verification=verification)
    document = _document(REPLAY, summary, header["config"], header["pins"],
                         capture_block=capture_block, capture_complete=complete,
                         offline_replay=PASS if complete else PREFIX_ONLY, session=None,
                         audit={"started_at": None, "ended_at": None},
                         synapse_cdm_version=synapse_cdm_version)
    return _finished(document)


def observe_run(summary: dict, config_document: dict, pins: dict, *, started_at_us: int,
                ended_at_us: int, synapse_cdm_version: str | None) -> bytes:
    """The `run.json` of a live run directory, from `host.run_session`'s summary, the validated
    configuration, the pin map the header recorded and the audit times (microseconds since
    1970, the wall clock at the command's start and end: audit only, R15). Written after live
    closure, so it says whether the capture is complete (CR-R6-F8)."""
    capture_block = _capture_block(summary, status=summary["status"],
                                   reason_code=summary["reason_code"],
                                   last_seq=summary["last_seq"], verification=None)
    session = {"terminal_codes": list(summary["terminal_codes"]), "workers": summary["workers"],
               "last_generation": summary["last_generation"]}
    audit = {"started_at": _utc.format_microsecond(started_at_us),
             "ended_at": _utc.format_microsecond(ended_at_us)}
    document = _document(OBSERVE, summary, config_document, pins, capture_block=capture_block,
                         capture_complete=summary["status"] == capture.COMPLETE,
                         offline_replay=NOT_RUN, session=session,
                         audit=audit, synapse_cdm_version=synapse_cdm_version)
    return _finished(document)
