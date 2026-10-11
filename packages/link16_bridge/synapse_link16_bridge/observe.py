"""Counters, gauges, histograms, the audit trail and the log (REQ150, REQ151).

Counter names are REQ150's thirteen, plus `fed`, the accounting total of REQ162 (every record of
a committed batch, and every record a gateway's loss accounting names at a resynchronisation):
`fed = accepted + refused + duplicate + dropped_by_capacity` after every batch. `unsupported`,
`duplicate_conflict` and `late` are sub-counts: an unsupported or conflicting record is also
`refused`, a late one also `accepted`.

Labels are closed enumerations (`LABELS`): a capability or an error code, never a track number, a
coordinate or a participant identifier. The log takes fixed text and closed-enum codes only, and
never a payload. Every refusal and every transmission writes one audit row with its correlation
identifier, the record or request identifier, the contract profile, the configuration revision,
the policy result, the transformation list and the raw evidence reference (REQ151).
"""
from __future__ import annotations

import bisect
import json
import logging
import uuid
from typing import Callable, Iterable

from synapse_link16_bridge.store import SQL_AUDIT_INSERT, Store

COUNTERS = ("accepted", "refused", "unsupported", "duplicate", "duplicate_conflict", "late",
            "time_skew", "dropped_by_capacity", "source_drop", "export_denied", "encoded", "sent",
            "unknown_send_outcome")
GAUGES = ("native_readiness", "queue_depth", "queue_bytes", "oldest_unacked_age_ms",
          "active_identities", "stale_identities", "last_accepted_report_age_ms")
HISTOGRAMS = ("parse", "mapping", "outbox_commit", "export")
#: Upper bucket bounds in milliseconds; the last bucket is unbounded.
BUCKETS_MS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000)

#: The closed vocabulary of every label and log code the bridge emits.
LABELS = frozenset({
    # contract and runtime codes (SPEC section 16)
    "SCHEMA_INVALID", "JSON_INVALID", "LIMIT_EXCEEDED", "SYNTHETIC_MISMATCH",
    "SECURITY_CONTEXT_MISMATCH", "TIME_UNRESOLVED", "IDENTITY_SCOPE_UNRESOLVED",
    "REUSE_AMBIGUOUS", "UNSUPPORTED_MESSAGE", "UNSUPPORTED_FIELD_FORM",
    "NATIVE_PROFILE_INCOMPLETE", "CDM_SOURCE_CONFLICT", "ALTITUDE_DATUM_UNSUPPORTED",
    "VALUE_NOT_REPRESENTABLE", "DUPLICATE_CONFLICT", "CURSOR_EXPIRED", "STREAM_GAP",
    "SEND_OUTCOME_UNKNOWN",
    # bridge-local codes (D-30)
    "LIFECYCLE_CONTRADICTION", "EXPORT_DENIED", "POLICY_DENIED", "REALM_LOOP",
    "NUMBER_UNALLOCATED", "FAMILY_NOT_ALLOWED", "PROFILE_NOT_READY", "SOURCE_STALE",
    "TIME_SKEW", "CHANNEL_INCOMPLETE", "REQUEST_EXPIRED", "LEASE_LOST",
    "UNAUTHENTICATED", "FORBIDDEN", "REQUEST_ID_CONFLICT", "PROFILE_MISMATCH", "CURSOR_FUTURE",
    "CURSOR_FOREIGN", "NOT_FOUND", "CAPACITY", "PROVIDER_UNAVAILABLE", "BLOCKED_EXTERNAL_EVIDENCE",
    "SCHEMA_NEGOTIATION_FAILED", "DURABLE_COMMIT_FAILED", "CAPACITY_REPORTS", "CAPACITY_EXPORTS",
    "CAPACITY_IDENTITIES", "CAPACITY_QUARANTINE", "STRUCTURAL_BATCH", "GATEWAY_IDENTITY_MISMATCH",
    "CONFIG_REVISION_RESTART", "GAP", "RESET_SCOPE", "TRANSPORT",
    "SINK_FAILED", "INTERNAL_ERROR",                    # A2F, 2026-10-11
    # capabilities and families of the synthetic profile
    "J3.2", "J3.3", "J3.4", "J3.5",
})

LOG = logging.getLogger("synapse_link16_bridge")


def log_event(event: str, code: str) -> None:
    """One log line: a fixed event phrase and a closed-enum code, nothing else."""
    LOG.info("%s: %s", event, code if code in LABELS else "OTHER")


class Histograms:
    """Fixed-bucket counts per histogram name. The values are durations measured on this machine
    and are never evidence for the performance requirement (REQ161)."""

    def __init__(self) -> None:
        self.counts = {name: [0] * (len(BUCKETS_MS) + 1) for name in HISTOGRAMS}

    def observe(self, name: str, seconds: float) -> None:
        index = bisect.bisect_left(BUCKETS_MS, seconds * 1000.0)
        self.counts[name][index] += 1

    def snapshot(self) -> dict:
        return {name: {"buckets_ms": list(BUCKETS_MS), "counts": list(counts)}
                for name, counts in self.counts.items()}


class Auditor:
    """Writes audit rows inside the caller's transaction."""

    def __init__(self, store: Store, config_revision: str, profile_version: str,
                 uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4) -> None:
        self.store = store
        self.config_revision = config_revision
        self.profile_version = profile_version
        self.uuid_factory = uuid_factory

    def record(self, kind: str, *, subject_id: str | None = None, code: str | None = None,
               policy_result: str | None = None, transformations: Iterable[str] = (),
               raw_ref: str | None = None, detail: str | None = None) -> str:
        correlation_id = str(self.uuid_factory())
        if detail is not None:
            detail = detail[:1024]
        self.store.db.execute(SQL_AUDIT_INSERT, (
            self.store.now(), correlation_id, kind, subject_id, code, self.profile_version,
            self.config_revision, policy_result, json.dumps(list(transformations)), raw_ref,
            detail, self.store.fence))
        return correlation_id
