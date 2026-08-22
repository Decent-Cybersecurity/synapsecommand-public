"""The never-drop rule, made checkable.

"Unmappable fields go into attributes/payload, never dropped" is the single most important
rule in the brief, and a rule that is only written down is a rule that decays. Lossy adapters
are what kill integration layers, and they do it quietly: the field stops arriving, nobody
notices for a quarter, and by then three consumers have been built on its absence.

So the rule is enforced by comparison. `unrepresented()` harvests every scalar leaf from the
source payload, harvests every scalar the CDM output holds, and reports the source values that
appear NOWHERE in the output. The harness fails an adapter on a non-empty report.

WHY VALUE-PRESENCE AND NOT KEY-PRESENCE
---------------------------------------
Keys are renamed by design — that is what translation IS. `alert_time` becomes `observed_at`,
`band` becomes `frequency_band`. Comparing keys would flag every correct translation. Values
survive translation, so values are what can be compared without knowing the mapping — which
is also what makes this check ADAPTER-AGNOSTIC, and the harness has to be adapter-agnostic to
be of any use to the adapter factory.

THE DECLARED-TRANSFORM ESCAPE, AND WHY IT IS LOUD
-------------------------------------------------
Some values legitimately change: knots to metres per second, a source's "jamming" to the enum
JAMMING, a rounded coordinate. An adapter declares those source paths in `TRANSFORMS`, with a
reason, and the check exempts them. The reasons are PRINTED in the harness report on every
run — an exemption is a visible line in the output, not a silent skip. An adapter that wanted
to hide a dropped field would have to write down that it was dropping it.

`_normalise` compares stringified, case-folded, whitespace-stripped forms so that 4.0 == "4",
True == "true" and 1e3 == "1000.0" do not read as data loss. Numbers additionally match on
their float value, because 71.5 and 71.50 are the same measurement written twice.
"""
from __future__ import annotations

from typing import Any, Iterable

# Values too common to prove anything by their presence. `None` is the absence of data, and
# an empty string or list carries no value to lose. Booleans and small integers are NOT here:
# a dropped `"estimated": true` is exactly the kind of loss this check exists to catch.
_UNINTERESTING: tuple[Any, ...] = (None, "", [], {})

# Distinct from None, which is a legitimate value a source can send.
_DROPPED = object()


def _normalise(value: Any) -> set[str]:
    """Every string form a value could legitimately appear as in the output.

    Numeric coercion runs on STRINGS too, not only on numbers. A CDM field may hold a figure
    as text — `Source.value` in the platform's own output contract does exactly that, for the
    documented reason that a local model writes a number as often as it quotes one — so
    comparing 71.5 against the string "71.50" has to succeed or the lossless check reports a
    loss that did not happen. A false positive here is expensive in a specific way: it teaches
    an adapter author to reach for TRANSFORMS to silence the harness, which is how the one
    escape hatch that has to stay meaningful gets devalued.
    """
    forms = {str(value).strip().casefold()}
    if isinstance(value, bool):
        forms.add(str(value).casefold())
        return {f for f in forms if f}
    try:
        as_float = float(str(value).strip())
    except (TypeError, ValueError):
        return {f for f in forms if f}
    forms.add(repr(as_float))
    forms.add(str(as_float))
    if as_float.is_integer():
        forms.add(str(int(as_float)))
    return {f for f in forms if f}


def leaves(value: Any, path: str = "") -> dict[str, Any]:
    """Every scalar in a nested structure, keyed by dotted path. Lists index numerically."""
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            found.update(leaves(sub, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            found.update(leaves(sub, f"{path}[{index}]"))
    else:
        found[path] = value
    return found


def _present_forms(objects: Iterable[dict]) -> set[str]:
    forms: set[str] = set()
    for obj in objects:
        for leaf in leaves(obj).values():
            if leaf in _UNINTERESTING:
                continue
            forms |= _normalise(leaf)
        # Keys count as present too: a source field parked as `attributes.receiver_count`
        # keeps its NAME as evidence even where the value is a common number.
        for path in leaves(obj):
            forms.add(path.rsplit(".", 1)[-1].casefold())
    return forms


def unrepresented(raw: Any, cdm_objects: Iterable[dict],
                  transforms: dict[str, str] | None = None) -> dict[str, Any]:
    """Source leaves whose value appears nowhere in the CDM output and is not declared.

    Returns {source_path: value}. Empty means the adapter is lossless for this payload.

    A `transforms` key matches either an exact dotted path or a prefix of one, so an adapter
    can declare a whole subtree (`vendor` covers `vendor.firmware`) without listing leaves it
    has never seen — which matters because the paths a source will invent next are not
    knowable in advance.
    """
    transforms = transforms or {}
    present = _present_forms(cdm_objects)
    missing: dict[str, Any] = {}
    for path, value in leaves(raw).items():
        if value in _UNINTERESTING:
            continue
        if any(path == declared or path.startswith(f"{declared}.")
               or path.startswith(f"{declared}[") for declared in transforms):
            continue
        if not (_normalise(value) & present):
            missing[path] = value
    return missing


def residual(raw: Any, consumed: Iterable[str]) -> Any:
    """Everything in `raw` the adapter did NOT consume, with its structure preserved.

    An adapter lists the dotted paths it mapped to canonical fields and parks the return value
    of this function in `attributes` / `payload`. Written once here rather than per adapter,
    because "collect the leftovers" hand-rolled five times is five chances to forget a nested
    block — and the block a source adds in its next firmware release is exactly the one nobody
    remembered to collect.

    Prefix semantics match `unrepresented()`: declaring `vendor` consumes the whole subtree,
    and `list[0]` addresses one element.

    STRUCTURE-PRESERVING, and the first version was not. Rebuilding the leftovers from dotted
    leaf paths turned `["GPS", "GALILEO"]` into two keys named `affected_constellations[0]`
    and `affected_constellations[1]`. Nothing was lost by the harness's measure — both values
    were present, so the lossless check passed — and yet a consumer could no longer read the
    field as a list. That is the never-drop rule being satisfied in the letter and broken in
    the meaning, so the prune is structural: it walks the object and removes consumed paths,
    rather than harvesting leaves and guessing at the shape on the way back.
    """
    consumed = list(consumed)

    def _is_consumed(path: str) -> bool:
        return any(path == c for c in consumed)

    def _has_consumed_descendant(path: str) -> bool:
        return any(c.startswith(f"{path}.") or c.startswith(f"{path}[") for c in consumed)

    def _walk(value: Any, path: str) -> Any:
        if _is_consumed(path):
            return _DROPPED
        if isinstance(value, dict):
            kept = {}
            for key, sub in value.items():
                here = f"{path}.{key}" if path else str(key)
                result = _walk(sub, here)
                if result is not _DROPPED:
                    kept[key] = result
            # An empty dict that had children means every child was consumed — drop the husk.
            # An empty dict that arrived empty is kept, because "the source sent an empty
            # object here" is itself information an adapter must not invent or erase.
            if not kept and (value or _has_consumed_descendant(path)):
                return _DROPPED
            return kept
        if isinstance(value, (list, tuple)):
            kept_items = []
            for index, sub in enumerate(value):
                result = _walk(sub, f"{path}[{index}]")
                if result is not _DROPPED:
                    kept_items.append(result)
            if not kept_items and (value or _has_consumed_descendant(path)):
                return _DROPPED
            return kept_items
        return value

    pruned = _walk(raw, "")
    return {} if pruned is _DROPPED else pruned
