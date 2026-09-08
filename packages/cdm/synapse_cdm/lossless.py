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

from typing import TYPE_CHECKING, Any, Iterable

from synapse_cdm.models import Residual

if TYPE_CHECKING:                      # pragma: no cover - typing only
    from synapse_cdm.adapter import Adapter

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


def residual_block(adapter: "Adapter", raw: Any, consumed: Iterable[str]) -> Residual:
    """`residual()`'s leftovers, wrapped in the origin-identifying container of §28.

    The namespace is READ FROM THE ADAPTER'S DECLARATION — `metadata.format.name`, the same
    string `source_ref()` stamps into `SourceRef.format_name` and the same string
    `manifests/<id>.json` publishes. Not a parameter, deliberately: an adapter free to name its
    own residual namespace could file leftovers under a format that is not the one it parsed, and
    then the container's ONE promise (a reader can find out whose vocabulary a key belongs to)
    would hold only by convention. One declaration, projected everywhere it is needed.

    Returns a `Residual` even when nothing was left over — `data` is then `{}` — because the
    caller is the one that decides whether an empty residual is worth attaching, and a helper
    that returned `None` for "nothing left" would make every call site write the same branch. An
    adapter that wants the field absent tests `block.data` and passes `None`.

    THE FOURTEEN ADAPTERS SHIPPED IN THIS REPOSITORY DO NOT CALL THIS, and that is
    ARCHITECTURE.md §5's ruling rather than an oversight: they keep their `attributes` /
    `payload` parking under `source_extras` through Part 1 and declare `residual: legacy`. This
    exists for the Part 2 adapters, which declare `residual: structured`, and it exists NOW so
    that the first of them is written against a helper rather than against a shape it invents.
    """
    return Residual(namespace=adapter.metadata.format.name, data=residual(raw, consumed))


# ---------------------------------------------------------------------- §34's six categories
#
# WHAT `unrepresented()` COULD NOT SAY, AND WHY A SECOND FUNCTION RATHER THAN A WIDER ONE
# ----------------------------------------------------------------------------------------
# `unrepresented()` answers one question — "did this value survive at all?" — and answers it
# well enough to gate fourteen adapters. It cannot answer the question §34 asks, which is
# WHERE a value went and BY WHAT LICENCE. A field that arrived in `attributes` and a field
# that arrived in a canonical slot are both "present" to the check above, and they are not the
# same fact about a translation: the first is parked and the second is mapped, and an
# integrator choosing an adapter needs to know which.
#
# So `classify()` is a strictly finer partition of the same leaves, and the arithmetic ties the
# two together rather than leaving them to agree: DROPPED is `unrepresented()`'s set minus the
# paths a limitation declares UNSUPPORTED, and `tests/test_cdm_lossless.py` asserts that
# identity per adapter per fixture rather than trusting this paragraph.
#
# THE PRECEDENCE IS DECLARATION-FIRST, AND THAT IS THE RULING
# -----------------------------------------------------------
# A declared transform wins over an observed presence. A knots-to-metres conversion whose source
# figure happens to appear elsewhere in the output would otherwise be reported PRESERVED, and
# the report would then say the value survived verbatim when what survived was a coincidence.
# Declarations are what the adapter is accountable for; presence is what this module measured.
# Reporting the accountable fact first is what makes the six categories auditable.

#: The subtrees that hold PARKED source data rather than mapped fields. Three of them are
#: `suite.PARKED` — the legacy parking every adapter in this repository declares (`residual:
#: legacy`, ARCHITECTURE.md §5) — and `residual` is §28's structured container, which Part 2's
#: adapters use. A leaf reached through any of them is RESIDUAL and not PRESERVED.
PARKED_KEYS: tuple[str, ...] = ("attributes", "payload", "source_extras", "residual")

#: The marker that turns a declared transform from NORMALIZED into DERIVED (M's pre-ruled
#: default 2). It lives in the REASON string of the existing `TRANSFORMS` map rather than in a
#: second `DERIVATIONS` map, because a second map is a second place to forget a path, and the
#: reason is already required, already printed by the harness on every run, and already the
#: thing an auditor reads.
DERIVED_MARKER = "derived:"

#: §34's six, in §34's order. Exported so the suite's text summary and the badge writer cannot
#: invent a seventh or drop one.
CATEGORIES: tuple[str, ...] = ("PRESERVED", "NORMALIZED", "DERIVED", "RESIDUAL", "UNSUPPORTED",
                               "DROPPED")


class LossReport:
    """Every source leaf, in exactly one of §34's six categories.

    A class rather than a dict so that the six names are fixed at one site, and so that
    `as_dict()` — which is what goes into the conformance JSON and into the evidence record —
    has one definition instead of one per caller.
    """

    __slots__ = CATEGORIES

    def __init__(self, **buckets: list[str]) -> None:
        for name in CATEGORIES:
            setattr(self, name, tuple(sorted(buckets.get(name, ()))))

    @property
    def total(self) -> int:
        return sum(len(getattr(self, name)) for name in CATEGORIES)

    def as_dict(self) -> dict:
        """The published shape: the six lists, plus their counts and the total.

        The counts are computed here and not by the caller, because a summary line that counted
        for itself is a second arithmetic that can disagree with the list beside it.
        """
        paths = {name: list(getattr(self, name)) for name in CATEGORIES}
        return {"paths": paths,
                "counts": {name: len(paths[name]) for name in CATEGORIES},
                "total": self.total}

    def summary_lines(self) -> list[str]:
        """§34's six-line summary, for `--format text`. One line per category, always all six."""
        width = max(len(name) for name in CATEGORIES)
        return [f"  {name.ljust(width)}  {len(getattr(self, name))}" for name in CATEGORIES]

    def __repr__(self) -> str:                       # pragma: no cover - debugging convenience
        counts = ", ".join(f"{n}={len(getattr(self, n))}" for n in CATEGORIES)
        return f"LossReport({counts})"


def _harvest(objects: Iterable[dict]) -> tuple[set[str], set[str]]:
    """(forms reached through no parked key, forms reached through one).

    Two harvests of one structure rather than two walks of two structures, because the question
    is about the PATH a leaf sits on and not about which object it came from.
    """
    canonical: set[str] = set()
    parked: set[str] = set()

    def walk(node: Any, under_parked: bool) -> None:
        target = parked if under_parked else canonical
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, under_parked or key in PARKED_KEYS)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value, under_parked)
            return
        if node not in _UNINTERESTING:
            target |= _normalise(node)

    def walk_keys(node: Any, under_parked: bool) -> None:
        target = parked if under_parked else canonical
        if isinstance(node, dict):
            for key, value in node.items():
                nested = under_parked or key in PARKED_KEYS
                # The KEY counts as evidence exactly as it does in `_present_forms`: a source
                # field parked under its own name keeps that name as the proof it arrived.
                (parked if nested else target).add(str(key).casefold())
                walk_keys(value, nested)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk_keys(value, under_parked)

    for obj in objects:
        walk(obj, False)
        walk_keys(obj, False)
    return canonical, parked


def _declared(path: str, declarations: Iterable[str]) -> str | None:
    """The declaration covering `path`, with `unrepresented()`'s own prefix semantics."""
    for declared in declarations:
        if (path == declared or path.startswith(f"{declared}.")
                or path.startswith(f"{declared}[")):
            return declared
    return None


def classify(raw: Any, cdm_objects: Iterable[dict],
             transforms: dict[str, str] | None = None,
             unsupported: Iterable[str] = ()) -> LossReport:
    """§34's loss report for one payload.

    `transforms` is the adapter's `TRANSFORMS` map — path to reason. A reason beginning
    `derived:` (see `DERIVED_MARKER`) puts the path in DERIVED; any other reason puts it in
    NORMALIZED. `unsupported` is `manifest.unsupported_paths(metadata.limitations)`: the
    machine-readable half of §34's "explicit documented exception", and the ONLY thing that
    moves a path out of DROPPED without the value being anywhere in the output.
    """
    transforms = transforms or {}
    unsupported = tuple(unsupported)
    objects = list(cdm_objects)
    canonical, parked = _harvest(objects)
    buckets: dict[str, list[str]] = {name: [] for name in CATEGORIES}
    for path, value in leaves(raw).items():
        if value in _UNINTERESTING:
            continue
        declared = _declared(path, transforms)
        if declared is not None:
            reason = transforms[declared]
            kind = "DERIVED" if reason.strip().lower().startswith(DERIVED_MARKER) else "NORMALIZED"
            buckets[kind].append(path)
            continue
        if _declared(path, unsupported) is not None:
            buckets["UNSUPPORTED"].append(path)
            continue
        forms = _normalise(value)
        if forms & canonical:
            buckets["PRESERVED"].append(path)
        elif forms & parked:
            buckets["RESIDUAL"].append(path)
        else:
            buckets["DROPPED"].append(path)
    return LossReport(**buckets)
