"""Source identities: the identity tuple, reuse, tombstones and the identity cap (REQ070-074,
REQ122).

The identity key is the adapter's own text: the compact JSON tuple `[tenant, realm, synthetic,
origin_scope, track_number, incarnation]` in that order, the same string the adapter writes into
`source_ids[0].external_id`, and the Entity and Track identifiers are the adapter's UUID5 of it.
Reporter, session, gateway, record and sequence are provenance and never part of it, so a
reconnect or a relaying participant never renumbers a track. The incarnation is the report's and
is never computed here; a timeout never advances it (REQ072).

AMBIGUOUS REUSE (REQ072, I03; the bridge's definition)
------------------------------------------------------
A report is ambiguous reuse, quarantined as `REUSE_AMBIGUOUS`, when (a) its tuple was closed by a
`DROP_SOURCE` (tombstoned) and its `effective_at` is later than the drop, or (b) a higher
incarnation of the same (scope, track number) is already known and this report is later than that
incarnation's first report — whether or not the report's own tuple was seen before (fix round 1,
2026-10-11: a lower incarnation that was LIVE is held to the rule too) — or (c) its tuple belongs
to a delivery epoch an operator closed with `resync-identities --decision advance`. A report of
a tombstoned tuple at or before the drop is late history and is accepted as such. The provider
resolves reuse by allocating the next incarnation: a report at a higher incarnation is a new
identity, and the quarantined reports of the lower one are closed `SUPERSEDED_BY_INCARNATION`.
An operator may also release a quarantined report (`resolve-reuse --decision continue`, a
recorded deviation from "await provider resolution") or keep it refused (`--decision reject`);
both are audited and both apply to a quarantine under any of the three rules. `continue`
records the decision on the tuple (admitting it as a LIVE identity when rule (b) never let it
in) together with its scope, the highest incarnation of the same (scope, track number) known when
it was recorded: later reports of that tuple are not held to rule (b) against those incarnations,
but a higher incarnation that appears afterwards re-arms rule (b) for the tuple, because the
operator decided only against what was known (fix round 2, 2026-10-11; D-51). `reject` closes the
quarantined reports and admits nothing.

Tombstones are never evicted. At the identity cap no new identity is admitted, by a report or by
a `REKEY` notice's new tuple: the batch that would add one is not consumed and the channel reports
`CAPACITY_IDENTITIES` (REQ120, REQ122; the notice half since A2F, 2026-10-11). The bridge keeps no
in-memory sample cache: durable history holds every observation, so REQ122's in-memory bound of
100 samples per identity holds with none kept (the unread cache was removed in A2F, 2026-10-11).
"""
from __future__ import annotations

import dataclasses
import json

from synapse_cdm import ids
from synapse_cdm.adapters.link16_gateway import IDENTITY_SYSTEM, identity_key

from synapse_link16_bridge.store import (SQL_IDENTITY_COUNT_LIVE, SQL_IDENTITY_GET,
                                         SQL_IDENTITY_INSERT, SQL_IDENTITY_SCOPE,
                                         SQL_QUARANTINE_RESOLVE, SQL_QUARANTINE_REUSE, Store)


TUPLE_FIELDS = ("tenant", "realm", "synthetic", "origin_scope", "track_number", "incarnation")


class CapacityStop(Exception):
    """A configured capacity is reached: the batch is not consumed (bounded backpressure)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclasses.dataclass(frozen=True)
class Decision:
    accept: bool
    late: bool = False
    code: str | None = None


def key_of(fields: dict) -> str:
    """The identity key of a report, a notice or an identity object (the six tuple keys)."""
    return identity_key(fields)


def entity_ids(key: str) -> tuple[str, str]:
    return (str(ids.derive(IDENTITY_SYSTEM, key, kind="entity")),
            str(ids.derive(IDENTITY_SYSTEM, key, kind="track")))


def insert(store: Store, key: str, fields: dict, status: str, epoch: int,
           first_effective_at: int | None, tombstone_at: int | None = None,
           tombstone_record_id: str | None = None) -> None:
    entity_id, track_id = entity_ids(key)
    store.db.execute(SQL_IDENTITY_INSERT, (
        key, fields["tenant"], fields["realm"], int(fields["synthetic"]), fields["origin_scope"],
        fields["track_number"], fields["incarnation"], entity_id, track_id, status, epoch,
        tombstone_at, tombstone_record_id, first_effective_at, None, store.fence))


def fields_of(key: str) -> dict:
    """The six tuple fields of an identity key the bridge wrote (the inverse of `key_of`)."""
    values = json.loads(key)
    return dict(zip(TUPLE_FIELDS, values, strict=True))


def highest_incarnation(siblings: list) -> int | None:
    """The highest incarnation among the identities of one (scope, track number)."""
    return max((int(sibling_incarnation) for _s, sibling_incarnation, _f, _t in siblings),
               default=None)


def _newer_incarnation_first(siblings: list, incarnation: int, effective_at: int) -> bool:
    """Rule (b): an incarnation above `incarnation` of the same (scope, track number) is known
    and its first report is earlier than this one."""
    return any(int(sibling_incarnation) > incarnation and first_effective_at is not None and
               effective_at > first_effective_at
               for _sibling, sibling_incarnation, first_effective_at, _status in siblings)


def resolve(store: Store, report: dict, effective_at: int, *, epoch: int, max_identities: int,
            now: int) -> Decision:
    """Decide whether a translated report's identity is admitted, inside the open transaction."""
    key = key_of(report)
    incarnation = int(report["incarnation"])
    siblings = store.db.execute(SQL_IDENTITY_SCOPE, (
        report["tenant"], report["realm"], int(report["synthetic"]), report["origin_scope"],
        report["track_number"])).fetchall()
    row = store.db.execute(SQL_IDENTITY_GET, (key,)).fetchone()
    if row is not None:
        status, tombstone_at, reuse_decision, reuse_scope = row[9], row[11], row[14], row[15]
        if status == "LIVE":
            # a recorded `continue` exempts the tuple from rule (b) only against the
            # incarnations known when it was recorded (up to `reuse_scope`)
            floor = incarnation
            if reuse_decision == "continue" and reuse_scope is not None:
                floor = max(incarnation, int(reuse_scope))
            if _newer_incarnation_first(siblings, floor, effective_at):
                return Decision(False, code="REUSE_AMBIGUOUS")
            return Decision(True)
        if status == "TOMBSTONED":
            if tombstone_at is not None and effective_at <= tombstone_at:
                return Decision(True, late=True)
            return Decision(False, code="REUSE_AMBIGUOUS")
        return Decision(False, code="REUSE_AMBIGUOUS")          # RESET: a closed epoch
    if _newer_incarnation_first(siblings, incarnation, effective_at):
        return Decision(False, code="REUSE_AMBIGUOUS")
    live = store.db.execute(SQL_IDENTITY_COUNT_LIVE).fetchone()[0]
    if live >= max_identities:
        raise CapacityStop("CAPACITY_IDENTITIES")
    insert(store, key, report, "LIVE", epoch, effective_at)
    for sibling, sibling_incarnation, _first, _status in siblings:
        if int(sibling_incarnation) < incarnation:
            for quarantine_id, *_rest in store.db.execute(SQL_QUARANTINE_REUSE,
                                                          (sibling,)).fetchall():
                store.db.execute(SQL_QUARANTINE_RESOLVE, (now, "SUPERSEDED_BY_INCARNATION",
                                                          store.fence, quarantine_id))
    return Decision(True)

