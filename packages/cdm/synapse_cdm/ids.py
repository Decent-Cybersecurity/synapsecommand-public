"""Stable identity: the same source object gets the same UUID on every update, forever.

`entity_id` is specified as "stable across updates". A random uuid4 per payload satisfies the
type and defeats the purpose: the tenth position report for one vessel would create ten
entities, the map would show ten contacts, and a track would never accumulate.

So identity is DERIVED, not drawn: uuid5 over (system, external_id) inside a fixed namespace.
That makes it a pure function of the source's own identifier, which has three consequences
worth stating —

1. Two adapters given the same (system, external_id) agree without coordinating. No id
   service, no registry lookup, nothing to be unavailable in an air-gapped node.
2. Golden-output tests are possible at all. A derived id is deterministic; a drawn one makes
   every run differ from every other run and there is nothing to diff against.
3. An adapter with no stable upstream identifier cannot fake one. It must say what it keyed
   on — see `derive()`'s `basis` return — and the harness prints that basis, so "this source
   has no stable id" is visible in the report instead of hidden behind a fresh uuid4.

The namespace is a fixed UUID, not uuid.NAMESPACE_URL with a made-up URL, because the CDM's
id space is its own and must not collide with anything else that hashes URLs.
"""
from __future__ import annotations

import uuid

# Fixed for the lifetime of CDM major version 1. Changing it renumbers every entity in every
# store that ever held CDM data, which is a MAJOR migration and nothing less.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")

SEPARATOR = "|"


def derive(system: str, external_id: str, kind: str = "entity") -> uuid.UUID:
    """The id for `external_id` as issued by `system`.

    `kind` separates the id spaces of the object types, so an event and an entity keyed on the
    same source identifier do not collide — a single PNTMAP alert legitimately produces both.
    """
    if not system or not external_id:
        raise ValueError("both system and external_id are required to derive a stable id")
    return uuid.uuid5(NAMESPACE, SEPARATOR.join((kind, system, str(external_id))))


def derive_with_basis(system: str, candidates: dict[str, str | None],
                      kind: str = "entity") -> tuple[uuid.UUID, str]:
    """Derive from the first candidate key that has a value; report WHICH one was used.

    Adapters take identifiers in order of preference (a real emitter id, then a report id,
    then a positional key) and the choice matters: an id keyed on a per-report field is stable
    for that report and NOT stable for the object across reports. Returning the basis makes
    that difference reportable instead of a footnote nobody reads.
    """
    for basis, value in candidates.items():
        if value not in (None, ""):
            return derive(system, str(value), kind=kind), basis
    raise ValueError(
        f"no usable identifier for a {kind} from {system}: all candidates empty "
        f"({', '.join(candidates)})"
    )
