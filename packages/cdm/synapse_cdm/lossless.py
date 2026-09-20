"""The never-drop rule, made checkable.

"Unmappable fields go into attributes/payload, never dropped" is the single most important
rule in the brief, and a rule that is only written down is a rule that decays. Lossy adapters
are what kill integration layers, and they do it quietly: the field stops arriving, nobody
notices for a quarter, and by then three consumers have been built on its absence.

So the rule is enforced by comparison. `value_presence_heuristic()` harvests every scalar leaf
from the source payload, harvests every scalar the CDM output holds, and reports the source
values that appear NOWHERE in the output. The harness fails an adapter on a non-empty report.

IT IS A HEURISTIC, AND ITS EMPTY RESULT IS NOT PROOF (audit remediation F02, 2026-09-19)
--------------------------------------------------------------------------------------
The comparison is over a SET of normalised scalars. `{"speed": 12, "heading": 12}` translated
to `[{"speed": 12}]` passes it: one surviving 12 satisfies both fields. A set of values cannot
say which source path a value came from, whether it arrived once or twice, at which array
index, or with which type. The function was renamed from `unrepresented()` so that no caller
can read its `{}` as "lossless": it catches a value that vanished outright, and nothing finer.
Proof lives in `ledger()` below — one entry per source LEAF, bound to a declared destination
and a declared rule — and the harness's `lossless` column carries the ledger's verdict wherever
an adapter declares `MAPPINGS`, and says `basis: heuristic` where it does not.

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

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable

from synapse_cdm import times
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


def value_presence_heuristic(raw: Any, cdm_objects: Iterable[dict],
                             transforms: dict[str, str] | None = None) -> dict[str, Any]:
    """Source leaves whose value appears nowhere in the CDM output and is not declared.

    Returns {source_path: value}. A non-empty result is a loss; an EMPTY RESULT IS NOT PROOF of
    preservation (see the module docstring's counterexample). Named for what it is since the
    audit remediation of 2026-09-19; it was `unrepresented()` before.

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

    Prefix semantics match `value_presence_heuristic()`: declaring `vendor` consumes the whole subtree,
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
# WHAT THE HEURISTIC COULD NOT SAY, AND WHY A SECOND FUNCTION RATHER THAN A WIDER ONE
# ----------------------------------------------------------------------------------------
# `value_presence_heuristic()` answers one question — "did this value survive at all?" — and answers it
# well enough to gate fourteen adapters. It cannot answer the question §34 asks, which is
# WHERE a value went and BY WHAT LICENCE. A field that arrived in `attributes` and a field
# that arrived in a canonical slot are both "present" to the check above, and they are not the
# same fact about a translation: the first is parked and the second is mapped, and an
# integrator choosing an adapter needs to know which.
#
# So `classify()` is a strictly finer partition of the same leaves, and the arithmetic ties the
# two together rather than leaving them to agree: DROPPED is the heuristic's set minus the
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
    """The declaration covering `path`, with `value_presence_heuristic()`'s own prefix semantics."""
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


# ------------------------------------------- F02: the path-bound preservation ledger (2026-09-19)
#
# WHAT THE LEDGER IS, AND WHAT IT IS NOT
# --------------------------------------
# One entry per source LEAF — a scalar or an empty container, addressed by its full path with
# array indices, so `tags[0]` and `tags[1]` are two entries even when both hold "a", and
# `speed` and `heading` are two entries even when both hold 12. Each entry is in exactly one of
# four categories:
#
#   MAPPED               a declared `Mapping` names the destination object and path, and the
#                        observed value satisfies the declared rule within its tolerance;
#   RESIDUAL             the leaf sits at the SAME relative path, with the same value and type,
#                        under a parked subtree (`PARKED_KEYS`) — or under the destination a
#                        residual-kind Mapping declares for its subtree. Structure, not a set;
#   DECLARED_LIMITATION  a structured manifest Limitation names the path in `unsupported_paths`.
#                        Surfaced as a loss the adapter wrote down, never as MAPPED;
#   LOST                 none of the above, with a `loss` kind saying what was observed:
#                        MISSING, VALUE_MISMATCH, TYPE_MISMATCH, MULTIPLICITY, ORDER,
#                        WRONG_OBJECT, TRANSFORM_MISMATCH or UNDECLARED_RESIDUAL.
#
# A free-text `TRANSFORMS` reason exempts NOTHING here. A conversion is a `rule` with an id and
# a tolerance, and the ledger recomputes it: `scale` multiplies, `enum_map` looks the table up,
# `instant` parses both timestamps. A rule the output does not satisfy is TRANSFORM_MISMATCH.
#
# This distinguishes four things the heuristic conflated: SOURCE PRESERVATION (every leaf is
# MAPPED or RESIDUAL — the value is somewhere addressable), MAPPED MEANING (the leaf is MAPPED
# by a rule to a canonical slot), STRUCTURAL ROUND-TRIP (the harness's `roundtrip` column,
# under a declared tolerance) and BYTE-FOR-BYTE ROUND-TRIP (the same column under the `bytes`
# tolerance). Keeping a raw payload under `source_extras` establishes the first and cannot
# establish the second; a hash of it establishes neither.
#
# DIAGNOSTICS NAME PATHS AND TYPES, NEVER VALUES. An entry says which source path, which
# destination was expected under which rule, which destination was observed and of what type.
# The payload itself is the adapter's input and may be sensitive; the report is published.

LEDGER_CATEGORIES: tuple[str, ...] = ("MAPPED", "RESIDUAL", "DECLARED_LIMITATION", "LOST")
LOSS_KINDS: tuple[str, ...] = ("MISSING", "VALUE_MISMATCH", "TYPE_MISMATCH", "MULTIPLICITY",
                               "ORDER", "WRONG_OBJECT", "TRANSFORM_MISMATCH",
                               "UNDECLARED_RESIDUAL")

#: Sentinel for "no value at this destination" — distinct from `None`, which a source can send.
_ABSENT = object()


class _Wild:
    """The `[*]` token: any array index, bound on match and substituted into the destination."""
    __slots__ = ()

    def __repr__(self) -> str:                       # pragma: no cover - debugging convenience
        return "[*]"


WILD = _Wild()
_BARE_KEY = re.compile(r'[^.\[\]"]+')


def parse_path(text: str) -> tuple:
    """`a.b[0].c` -> ("a", "b", 0, "c"); `[*]` -> WILD; a key holding `.`, `[`, `]` or `"` is
    written JSON-quoted: `"a.b".c` -> ("a.b", "c"). Matching is on TOKENS, so a separator inside
    a key can never be read as structure."""
    tokens: list = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            close = text.find("]", i)
            if close == -1:
                raise ValueError(f"unterminated index in path {text!r}")
            inner = text[i + 1:close]
            tokens.append(WILD if inner == "*" else int(inner))
            i = close + 1
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            if j >= n:
                raise ValueError(f"unterminated quoted key in path {text!r}")
            tokens.append(json.loads(text[i:j + 1]))
            i = j + 1
            continue
        match = _BARE_KEY.match(text, i)
        if match is None:
            raise ValueError(f"cannot read path {text!r} at offset {i}")
        tokens.append(match.group())
        i = match.end()
    return tuple(tokens)


def render_path(tokens: Iterable) -> str:
    """The inverse of `parse_path`, quoting a key the bare grammar could not carry."""
    out = ""
    for token in tokens:
        if isinstance(token, bool) or not isinstance(token, (int, _Wild)):
            key = token if _BARE_KEY.fullmatch(str(token)) else json.dumps(str(token))
            out += ("." if out else "") + key
        elif token is WILD:
            out += "[*]"
        else:
            out += f"[{token}]"
    return out


def type_name(value: Any) -> str:
    """The type vocabulary the diagnostics use. `absent` is not a type a source can send."""
    if value is _ABSENT:
        return "absent"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "empty_dict" if not value else "dict"
    if isinstance(value, (list, tuple)):
        return "empty_list" if not value else "list"
    return type(value).__name__


def typed_leaves(value: Any, path: tuple = ()) -> list[tuple[tuple, Any]]:
    """Every leaf as (tokens, value). Unlike `leaves()`, an EMPTY container is a leaf — "the
    source sent an empty list here" is a fact an adapter can lose — and nothing is filtered:
    `None`, `""`, `False` and `0` are values, each with its own type."""
    if isinstance(value, dict):
        if not value:
            return [(path, value)]
        found: list[tuple[tuple, Any]] = []
        for key, sub in value.items():
            found += typed_leaves(sub, path + (str(key),))
        return found
    if isinstance(value, (list, tuple)):
        if not value:
            return [(path, [])]
        found = []
        for index, sub in enumerate(value):
            found += typed_leaves(sub, path + (index,))
        return found
    return [(path, value)]


def _resolve(node: Any, tokens: tuple) -> Any:
    """The value at `tokens` inside `node`, or `_ABSENT`."""
    for token in tokens:
        if isinstance(token, int) and not isinstance(token, bool):
            if not isinstance(node, (list, tuple)) or token >= len(node):
                return _ABSENT
            node = node[token]
        else:
            if not isinstance(node, dict) or token not in node:
                return _ABSENT
            node = node[token]
    return node


# --------------------------------------------------------------------------- the declared rules
#
# A rule is `(source, observed, tolerance, params) -> None | reason`. `None` means the observed
# destination satisfies the declaration. Every rule is total over `observed is _ABSENT`: the
# ledger classifies an absent destination as MISSING before the rule runs, except for
# `absent_if`, which is the one rule whose expected outcome can BE absence.

def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _identical(source: Any, observed: Any) -> bool:
    if type_name(source) != type_name(observed):
        return False
    if _numeric(source):
        return float(source) == float(observed)
    return source == observed


def _rule_identity(source, observed, tolerance, params):
    return None if _identical(source, observed) else "not identical"


def _rule_number(source, observed, tolerance, params):
    if not _numeric(source) or not _numeric(observed):
        return "both sides must be numbers"
    return None if abs(float(source) - float(observed)) <= (tolerance or 0.0) else "outside tolerance"


def _rule_scale(source, observed, tolerance, params):
    if not _numeric(source) or not _numeric(observed):
        return "both sides must be numbers"
    expected = float(source) * float(params["factor"]) + float(params.get("offset", 0.0))
    return None if abs(expected - float(observed)) <= (tolerance or 0.0) else "outside tolerance"


def _rule_round(source, observed, tolerance, params):
    if not _numeric(source) or not _numeric(observed):
        return "both sides must be numbers"
    expected = round(float(source), int(params["decimals"]))
    return None if abs(expected - float(observed)) <= (tolerance or 0.0) else "outside tolerance"


def _rule_enum_map(source, observed, tolerance, params):
    key = str(source)
    if params.get("fold_case"):
        key = key.casefold()
        table = {str(k).casefold(): v for k, v in params["table"].items()}
    else:
        table = params["table"]
    if key in table:
        expected = table[key]
    elif "default" in params:
        expected = params["default"]
    else:
        return "source value is not in the declared table and no default is declared"
    return None if observed == expected else "observed is not the table's value"


def _rule_casefold(source, observed, tolerance, params):
    if not isinstance(source, str) or not isinstance(observed, str):
        return "both sides must be strings"
    return None if source.casefold() == observed.casefold() else "differs beyond case"


def _rule_text(source, observed, tolerance, params):
    if not isinstance(observed, str):
        return "observed is not a string"
    return None if str(source) == observed else "text differs"


def _rule_instant(source, observed, tolerance, params):
    try:
        a, b = times.parse(source), times.parse(observed)
    except (TypeError, ValueError):
        return "one side is not a timestamp"
    return None if abs((a - b).total_seconds()) <= (tolerance or 0.0) else "different instant"


def _rule_absent_if(source, observed, tolerance, params):
    if source == params["sentinel"]:
        return None if observed is _ABSENT or observed is None else "sentinel must become absent"
    if observed is _ABSENT:
        return "missing"
    return RULES[params.get("else", "identity")](source, observed, tolerance, params)


#: Every rule an adapter may declare. A `Mapping` naming a rule not in this table is refused at
#: declaration time, so an unknown id cannot read as a passed one.
RULES: dict[str, Callable[[Any, Any, float | None, dict], str | None]] = {
    "identity": _rule_identity, "number": _rule_number, "scale": _rule_scale,
    "round": _rule_round, "enum_map": _rule_enum_map, "casefold": _rule_casefold,
    "text": _rule_text, "instant": _rule_instant, "absent_if": _rule_absent_if,
}


@dataclass(frozen=True)
class Mapping:
    """One declared binding from a source path to one destination.

    `to` is `<target>:<path>`: the target is an `object_kind` (`entity`, `event`, `track`,
    `plan`), `#<index>` for a position in the output list, or `*` for any object — and `*`
    forfeits the WRONG_OBJECT diagnosis, so a shipped adapter names its kinds. `[*]` in the
    source key binds an array index that `[*]` in the path receives, in order.

    `kind="residual"` declares that the SUBTREE at the source key is parked, structure intact,
    under `to`, with the key's prefix replaced: the adapter that parks `interference.*` at
    `payload.source_extras.*` says so here, and the ledger checks each leaf of the subtree at the
    relative path that implies.
    """
    to: str
    rule: str = "identity"
    tolerance: float | None = None
    params: dict = field(default_factory=dict)
    kind: str = "field"

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"unknown preservation rule {self.rule!r}; known: {sorted(RULES)}")
        if self.kind not in ("field", "residual"):
            raise ValueError(f"Mapping.kind must be 'field' or 'residual', not {self.kind!r}")
        if self.kind == "residual" and self.rule != "identity":
            raise ValueError("a residual-kind Mapping is structure-preserving by definition and "
                             "takes no rule but identity")
        if ":" not in self.to:
            raise ValueError(f"a destination names its target object: '<target>:<path>', "
                             f"not {self.to!r}")
        parse_path(self.to.split(":", 1)[1])

    @property
    def target(self) -> str:
        return self.to.split(":", 1)[0]

    @property
    def path(self) -> tuple:
        return parse_path(self.to.split(":", 1)[1])


@dataclass(frozen=True)
class Entry:
    """One source leaf's line in the ledger. Carries paths, rules and types; never a value."""
    source_path: str
    category: str
    loss: str | None
    expected: dict
    observed: dict

    def as_dict(self) -> dict:
        return {"source_path": self.source_path, "category": self.category, "loss": self.loss,
                "expected": self.expected, "observed": self.observed}

    def line(self) -> str:
        exp = self.expected
        want = (f"{exp['destination']} by rule {exp['rule']}"
                + (f" (tolerance {exp['tolerance']})" if exp.get("tolerance") is not None else "")
                if exp.get("destination") else exp.get("rule", "nothing declared"))
        obs = self.observed
        seen = (f"{obs['destination']} of type {obs['type']}" if obs.get("destination")
                else f"nothing ({obs.get('type', 'absent')})")
        return f"{self.source_path}: {self.category}/{self.loss} — expected {want}; observed {seen}"


class Ledger:
    """Every source leaf, in exactly one of `LEDGER_CATEGORIES`."""

    def __init__(self, entries: list[Entry], declared_mappings: int) -> None:
        self.entries = tuple(entries)
        self.declared_mappings = declared_mappings

    @property
    def lost(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.category == "LOST")

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def counts(self) -> dict[str, int]:
        return {name: sum(1 for e in self.entries if e.category == name)
                for name in LEDGER_CATEGORIES}

    @property
    def losses(self) -> dict[str, int]:
        return {kind: sum(1 for e in self.entries if e.loss == kind) for kind in LOSS_KINDS}

    def as_dict(self, limit: int = 20) -> dict:
        """The published shape. `diagnostics` is LOST entries first, capped at `limit`; the
        counts are complete whatever the cap."""
        ordered = sorted(self.entries, key=lambda e: (e.category != "LOST", e.source_path))
        return {"basis": "ledger", "declared_mappings": self.declared_mappings,
                "counts": self.counts, "losses": self.losses, "total": self.total,
                "diagnostics": [e.as_dict() for e in ordered[:limit]],
                "diagnostics_truncated": max(0, len(ordered) - limit)}

    def problem_lines(self) -> list[str]:
        return [e.line() for e in sorted(self.lost, key=lambda e: e.source_path)]

    def __repr__(self) -> str:                       # pragma: no cover - debugging convenience
        return f"Ledger({', '.join(f'{k}={v}' for k, v in self.counts.items())})"


def _match_pattern(pattern: tuple, tokens: tuple, prefix: bool = False) -> list[int] | None:
    """Bindings for `[*]` when `pattern` matches `tokens` (or a prefix of them), else None."""
    if len(pattern) > len(tokens) or (not prefix and len(pattern) != len(tokens)):
        return None
    bound: list[int] = []
    for want, have in zip(pattern, tokens):
        if want is WILD:
            if isinstance(have, bool) or not isinstance(have, int):
                return None
            bound.append(have)
        elif want != have or type(want) is not type(have):
            return None
    return bound


def _substitute(path: tuple, bound: list[int]) -> tuple:
    out: list = []
    remaining = list(bound)
    for token in path:
        if token is WILD:
            if not remaining:
                raise ValueError(f"destination {render_path(path)} has more [*] than the "
                                 "source key binds")
            out.append(remaining.pop(0))
        else:
            out.append(token)
    return tuple(out)


def _targets(objects: list[dict], target: str) -> list[int]:
    if target == "*":
        return list(range(len(objects)))
    if target.startswith("#"):
        index = int(target[1:])
        return [index] if index < len(objects) else []
    return [i for i, obj in enumerate(objects)
            if isinstance(obj, dict) and obj.get("object_kind") == target]


def _parked_index(objects: list[dict]) -> dict[tuple, list[tuple[str, Any]]]:
    """Relative path -> [(absolute destination, value)] for every leaf under a parked subtree.

    A parked key nested in a parked key (`attributes.source_extras`) starts a second root, so a
    leaf is indexed both as `source_extras.x` and as `x`; §28's container is rooted at its
    `data`. Structure is what is indexed — a list stays a list — so a residual flattened to
    dotted keys cannot match here and is reported UNDECLARED_RESIDUAL by the caller.
    """
    index: dict[tuple, list[tuple[str, Any]]] = {}

    def walk(node: Any, absolute: tuple, roots: list[tuple], obj: int) -> None:
        if isinstance(node, dict) and node:
            for key, sub in node.items():
                here = absolute + (str(key),)
                nested = list(roots)
                if key in PARKED_KEYS:
                    root = here
                    if key == "residual" and isinstance(sub, dict) and "data" in sub:
                        root = here + ("data",)
                    nested.append(root)
                walk(sub, here, nested, obj)
            return
        if isinstance(node, (list, tuple)) and node:
            for i, sub in enumerate(node):
                walk(sub, absolute + (i,), roots, obj)
            return
        for root in roots:
            if len(absolute) > len(root) and absolute[:len(root)] == root:
                index.setdefault(absolute[len(root):], []).append(
                    (f"#{obj}:{render_path(absolute)}", node))

    for i, obj in enumerate(objects):
        walk(obj, (), [], i)
    return index


def _observed(destination: str | None, value: Any) -> dict:
    return {"destination": destination, "type": type_name(value)}


def _check_field(source: Any, mapping: Mapping, dest: tuple,
                 objects: list[dict]) -> tuple[str, str | None, dict]:
    """(category, loss, observed) for one declared destination of one leaf."""
    candidates = _targets(objects, mapping.target)
    rule = RULES[mapping.rule]
    first_failure: tuple[str, str | None, dict] | None = None
    for i in candidates:
        observed = _resolve(objects[i], dest)
        where = f"#{i}:{render_path(dest)}"
        if observed is _ABSENT and mapping.rule != "absent_if":
            parent = _resolve(objects[i], dest[:-1]) if dest else _ABSENT
            loss = ("MULTIPLICITY" if dest and isinstance(dest[-1], int)
                    and isinstance(parent, (list, tuple)) else "MISSING")
            failure = ("LOST", loss, _observed(None, _ABSENT))
        else:
            reason = rule(source, observed, mapping.tolerance, mapping.params)
            if reason is None:
                return "MAPPED", None, _observed(where, observed)
            if mapping.rule == "absent_if" and observed is _ABSENT:
                failure = ("LOST", "MISSING", _observed(None, _ABSENT))
            elif mapping.rule in ("identity", "number"):
                if type_name(source) != type_name(observed) and mapping.rule == "identity":
                    loss = "TYPE_MISMATCH"
                elif mapping.rule == "number" and not _numeric(observed):
                    loss = "TYPE_MISMATCH"
                else:
                    loss = "VALUE_MISMATCH"
                    if dest and isinstance(dest[-1], int):
                        siblings = _resolve(objects[i], dest[:-1])
                        if isinstance(siblings, (list, tuple)) and any(
                                rule(source, s, mapping.tolerance, mapping.params) is None
                                for j, s in enumerate(siblings) if j != dest[-1]):
                            loss = "ORDER"
                failure = ("LOST", loss, _observed(where, observed))
            else:
                failure = ("LOST", "TRANSFORM_MISMATCH", _observed(where, observed))
        first_failure = first_failure or failure
    if first_failure is not None and first_failure[1] != "MISSING":
        return first_failure
    # No object of the declared kind holds it. Is it in an object of another kind?
    for i, obj in enumerate(objects):
        if i in candidates:
            continue
        observed = _resolve(obj, dest)
        if observed is not _ABSENT:
            return "LOST", "WRONG_OBJECT", _observed(f"#{i}:{render_path(dest)}", observed)
    return first_failure or ("LOST", "MISSING", _observed(None, _ABSENT))


def ledger(raw: Any, cdm_objects: Iterable[dict], mappings: dict[str, Mapping | tuple | list],
           unsupported: Iterable[str] = ()) -> Ledger:
    """The path-bound preservation ledger for one payload.

    `mappings` is the adapter's `MAPPINGS`: source path (with `[*]`) -> `Mapping` or a tuple of
    them (a multi-object mapping: every destination must hold). `unsupported` is
    `manifest.unsupported_paths(metadata.limitations)`, prefix semantics, category
    DECLARED_LIMITATION. Everything undeclared is looked for under the parked subtrees at its
    own relative path, and nowhere else.
    """
    objects = list(cdm_objects)
    declared: list[tuple[tuple, tuple[Mapping, ...]]] = []
    for key, value in mappings.items():
        group = tuple(value) if isinstance(value, (tuple, list)) else (value,)
        for m in group:
            if not isinstance(m, Mapping):
                raise TypeError(f"MAPPINGS[{key!r}] holds {type(m).__name__}, not a Mapping")
        declared.append((parse_path(key), group))
    limits = [parse_path(p) for p in unsupported]
    parked = _parked_index(objects)
    entries: list[Entry] = []

    for tokens, value in typed_leaves(raw):
        path = render_path(tokens)
        entry: Entry | None = None
        for pattern, group in declared:
            residual_only = all(m.kind == "residual" for m in group)
            bound = _match_pattern(pattern, tokens, prefix=residual_only)
            if bound is None:
                continue
            remainder = tokens[len(pattern):] if residual_only else ()
            for m in group:
                dest = _substitute(m.path, bound) + remainder
                expected = {"destination": f"{m.target}:{render_path(dest)}", "rule": m.rule,
                            "tolerance": m.tolerance}
                category, loss, observed = _check_field(value, m, dest, objects)
                if category == "MAPPED" and m.kind == "residual":
                    category = "RESIDUAL"
                if category == "LOST" and m.kind == "residual" and loss == "MISSING":
                    if any(_identical(value, v) for rel, hits in parked.items()
                           for _, v in hits if rel != tokens):
                        loss = "UNDECLARED_RESIDUAL"
                entry = Entry(path, category, loss, expected, observed)
                if category == "LOST":
                    break
            break
        if entry is None:
            covering = next((lim for lim in limits if tokens[:len(lim)] == lim), None)
            if covering is not None:
                entry = Entry(path, "DECLARED_LIMITATION", None,
                              {"destination": None, "rule": f"limitation:{render_path(covering)}",
                               "tolerance": None}, _observed(None, _ABSENT))
        if entry is None:
            hits = parked.get(tokens, [])
            match = next(((where, v) for where, v in hits if _identical(value, v)), None)
            expected = {"destination": None, "rule": "residual at the same relative path",
                        "tolerance": None}
            if match is not None:
                entry = Entry(path, "RESIDUAL", None, expected, _observed(match[0], match[1]))
            elif hits:
                where, v = hits[0]
                loss = "TYPE_MISMATCH" if type_name(v) != type_name(value) else "VALUE_MISMATCH"
                entry = Entry(path, "LOST", loss, expected, _observed(where, v))
            elif any(_identical(value, v) for rel, hs in parked.items() for _, v in hs):
                entry = Entry(path, "LOST", "UNDECLARED_RESIDUAL", expected,
                              _observed(None, _ABSENT))
            else:
                entry = Entry(path, "LOST", "MISSING", expected, _observed(None, _ABSENT))
        entries.append(entry)
    return Ledger(entries, len(declared))
