"""Runtime capacity (REQ120-122): published caps, an 80 percent warning, a stop at 100 percent.

The caps are configuration with the specification's defaults: 100 000 active source identities
per channel; 10 000 queued reports or 64 MiB (outbox events not yet delivered to the sink),
whichever is first; 4 096 queued exports or 16 MiB (export jobs not yet in a final state); and a
quarantine of 1 GiB per channel (quarantined bodies and the raw batches kept as their evidence).
At 80 percent a warning is reported in `status` and counted (`capacity_warning`, once each time
a cap enters the band, with a log line naming the cap's code); at 100 percent new acceptance
stops — the bridge stops fetching, so the gateway's retention holds the records and nothing is
lost (bounded backpressure in gateway API mode, REQ121) — and health names the cap. Past the
quarantine cap, new refusals are kept as metadata only (code, path, rule, digest, no body and no
raw batch) and the `quarantine_metadata_only` alarm is counted and logged. Such a metadata row is
of the same order as the audit row REQ151 requires for every refusal and the ingest row the
deduplication keeps for every record; none of the three is deleted in this release (fix round 1,
2026-10-11). Nothing live is evicted: no identity mapping, no unacknowledged export, no
tombstone.

`full` names every cap at 100 percent, of every kind; `STOPS_FETCHING` is the one kind at which
the bridge stops fetching (the report queue). The channel's `OVERLOADED` state, and its `capacity`
and `capacity_cleared` audit rows, change only on a transition: a pass that finds the channel
held by the same cap writes nothing (A2F, 2026-10-11; before, an identity cap written once per
pass and cleared once per pass wrote two audit rows per idle pass).
"""
from __future__ import annotations

import dataclasses

from synapse_link16_bridge.store import (SQL_IDENTITY_COUNT_LIVE, SQL_JOBS_QUEUE, SQL_OUTBOX_QUEUE,
                                         SQL_QUARANTINE_BYTES, SQL_RAW_BYTES, Store)

WARNING_FRACTION = 0.8
#: The caps at which the bridge stops fetching. An export cap denies new exports, the identity
#: cap stops a batch that would add an identity, and the quarantine cap turns refusals into
#: metadata; none of those three stops the channel's ingest.
STOPS_FETCHING = ("CAPACITY_REPORTS",)


@dataclasses.dataclass(frozen=True)
class Usage:
    queued_reports: int
    queued_report_bytes: int
    oldest_queued_at: int | None
    queued_exports: int
    queued_export_bytes: int
    identities: int
    quarantine_bytes: int


def usage(store: Store) -> Usage:
    reports, report_bytes, oldest = store.db.execute(SQL_OUTBOX_QUEUE).fetchone()
    exports, export_bytes = store.db.execute(SQL_JOBS_QUEUE).fetchone()
    identities = store.db.execute(SQL_IDENTITY_COUNT_LIVE).fetchone()[0]
    quarantine = quarantine_bytes(store)
    return Usage(reports, report_bytes, oldest, exports, export_bytes, identities, quarantine)


def _pairs(used: Usage, limits: dict) -> list[tuple[str, float, float]]:
    return [
        ("CAPACITY_REPORTS", used.queued_reports, limits["max_queued_reports"]),
        ("CAPACITY_REPORTS", used.queued_report_bytes, limits["max_queued_report_bytes"]),
        ("CAPACITY_EXPORTS", used.queued_exports, limits["max_queued_exports"]),
        ("CAPACITY_EXPORTS", used.queued_export_bytes, limits["max_queued_export_bytes"]),
        ("CAPACITY_IDENTITIES", used.identities, limits["max_identities"]),
        ("CAPACITY_QUARANTINE", used.quarantine_bytes, limits["max_quarantine_bytes"]),
    ]


def full(used: Usage, limits: dict) -> list[str]:
    """Every cap at 100 percent, of every kind, each code once in the order of `_pairs`. Which of
    them stop fetching is `STOPS_FETCHING`."""
    out = []
    for code, value, cap in _pairs(used, limits):
        if value >= cap and code not in out:
            out.append(code)
    return out


def warnings(used: Usage, limits: dict) -> list[str]:
    out = []
    for code, value, cap in _pairs(used, limits):
        if value >= WARNING_FRACTION * cap and code not in out:
            out.append(code)
    return out


def exports_full(used: Usage, limits: dict) -> bool:
    return used.queued_exports >= limits["max_queued_exports"] or \
        used.queued_export_bytes >= limits["max_queued_export_bytes"]


def quarantine_bytes(store: Store) -> int:
    """The bytes the quarantine holds: quarantined bodies and raw batches kept as evidence."""
    return store.db.execute(SQL_QUARANTINE_BYTES).fetchone()[0] + \
        store.db.execute(SQL_RAW_BYTES).fetchone()[0]


def quarantine_full(store: Store, limits: dict) -> bool:
    return quarantine_bytes(store) >= limits["max_quarantine_bytes"]
