"""Lifecycle notices: DROP_SOURCE, REKEY, GAP and RESET_SCOPE (REQ064, REQ073, REQ105, REQ106).

Notices never reach the adapter (REQ064); `contract.validate_notice` judges them, the channel
check applies to them as to reports (without `gateway_id`, which a notice does not carry), and
they are deduplicated by the configured `gateway_id` and their `record_id`.

- `DROP_SOURCE` closes exactly the notice's identity tuple at its `effective_at`: a `close` event
  carrying a copy of the last published Entity with `valid_to` set (validated by the model), a
  tombstone, and the contribution marked closed; other tuples — other incarnations of the same
  number, other scopes — are untouched. A drop for a tuple with no published state records the
  tombstone and publishes nothing. A drop older than the identity's current state is a
  contradictory lifecycle history: with no native lifecycle resolver to confirm the order, it is
  quarantined as `LIFECYCLE_CONTRADICTION` (a bridge-local code) and the contribution stays open.
  The reporting-authority half of REQ105 cannot be checked, because a notice carries no reporter:
  it is not claimed.
- `REKEY` records a durable relation from the old tuple to the new one and publishes a `relation`
  event; both identities and both histories are kept and nothing is merged. Both tuples must be in
  this channel's tenant, realm and synthetic layer, and the notice's own number, incarnation and
  scope must be the old tuple's. A new tuple not yet known becomes a LIVE identity and is held to
  the identity cap like a report's (`CapacityStop`, `CAPACITY_IDENTITIES`: the batch is not
  consumed). An old tuple this channel has never seen is accepted: the relation is recorded all
  the same, as REQ073 asks (A2F, 2026-10-11).
- `GAP` marks the channel INCOMPLETE and blocks exports until an operator records recovery.
- `RESET_SCOPE` stops exports, closes the delivery epoch (epoch + 1) and requires a recorded
  identity resynchronisation decision; history is untouched.

A disconnect, an empty batch, a failed poll or a stale contribution is not a drop: nothing here
runs without a notice.
"""
from __future__ import annotations

import dataclasses

from synapse_cdm.models import Entity

from synapse_link16_bridge import identity, jsonstrict
from synapse_link16_bridge.clock import from_ms, parse_ms
from synapse_link16_bridge.state import publish
from synapse_link16_bridge.store import (CHANNEL, SQL_CHANNEL_EPOCH, SQL_CHANNEL_GAP,
                                         SQL_CURRENT_CLOSE, SQL_CURRENT_GET,
                                         SQL_IDENTITY_COUNT_LIVE, SQL_IDENTITY_GET,
                                         SQL_IDENTITY_TOMBSTONE, SQL_RELATION_INSERT, Store)


@dataclasses.dataclass(frozen=True)
class Outcome:
    accept: bool
    code: str | None = None
    path: str | None = None


def apply(store: Store, notice: dict, *, channel_epoch: int, tenant: str, realm: str,
          synthetic: bool, max_identities: int) -> Outcome:
    operation = notice["operation"]
    effective_at = parse_ms(notice["effective_at"], "effective_at")
    if operation == "DROP_SOURCE":
        return _drop(store, notice, effective_at, channel_epoch)
    if operation == "REKEY":
        return _rekey(store, notice, effective_at, channel_epoch, tenant, realm, synthetic,
                      max_identities)
    if operation == "GAP":
        store.db.execute(SQL_CHANNEL_GAP, ("GAP", None, None, store.fence, CHANNEL))
        return Outcome(True)
    store.db.execute(SQL_CHANNEL_EPOCH, (store.fence, CHANNEL))
    return Outcome(True)


def _drop(store: Store, notice: dict, effective_at: int, epoch: int) -> Outcome:
    key = identity.key_of(notice)
    row = store.db.execute(SQL_IDENTITY_GET, (key,)).fetchone()
    if row is None:
        identity.insert(store, key, notice, "TOMBSTONED", epoch, None, effective_at,
                        notice["record_id"])
        store.counter_add("source_drop")
        return Outcome(True)
    current = store.db.execute(SQL_CURRENT_GET, (key,)).fetchone()
    if current is not None and effective_at < current[2]:
        return Outcome(False, "LIFECYCLE_CONTRADICTION", "effective_at")
    if current is not None and current[7] == "ACTIVE":
        entity = Entity.model_validate_json(current[11])
        closed = Entity.model_validate(dict(entity.model_dump(), valid_to=from_ms(effective_at)))
        payload = jsonstrict.canonical(closed.model_dump(mode="json"))
        publish(store, f"{notice['record_id']}:0", "close", payload, closed.schema_version, [])
        store.db.execute(SQL_CURRENT_CLOSE, (store.fence, key))
    store.db.execute(SQL_IDENTITY_TOMBSTONE, (effective_at, notice["record_id"], store.fence, key))
    store.counter_add("source_drop")
    return Outcome(True)


def _rekey(store: Store, notice: dict, effective_at: int, epoch: int, tenant: str, realm: str,
           synthetic: bool, max_identities: int) -> Outcome:
    old, new = notice["old_identity"], notice["new_identity"]
    for name, tuple_ in (("old_identity", old), ("new_identity", new)):
        if (tuple_["tenant"], tuple_["realm"], tuple_["synthetic"]) != (tenant, realm, synthetic):
            return Outcome(False, "IDENTITY_SCOPE_UNRESOLVED", name)
    for key in ("origin_scope", "track_number", "incarnation"):
        if notice[key] != old[key]:
            return Outcome(False, "SCHEMA_INVALID", f"old_identity.{key}")
    old_key, new_key = identity.key_of(old), identity.key_of(new)
    if old_key == new_key:
        return Outcome(False, "SCHEMA_INVALID", "new_identity")
    if store.db.execute(SQL_IDENTITY_GET, (new_key,)).fetchone() is None:
        if store.db.execute(SQL_IDENTITY_COUNT_LIVE).fetchone()[0] >= max_identities:
            raise identity.CapacityStop("CAPACITY_IDENTITIES")
        identity.insert(store, new_key, new, "LIVE", epoch, effective_at)
    store.db.execute(SQL_RELATION_INSERT, (old_key, new_key, notice["record_id"], effective_at,
                                           notice["reason"], store.fence))
    old_entity, _ = identity.entity_ids(old_key)
    new_entity, _ = identity.entity_ids(new_key)
    payload = jsonstrict.canonical({"relation": "REKEY", "old_entity_id": old_entity,
                                    "new_entity_id": new_entity,
                                    "effective_at": notice["effective_at"]})
    publish(store, f"{notice['record_id']}:0", "relation", payload, None, [])
    return Outcome(True)
