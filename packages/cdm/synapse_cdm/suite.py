"""The Synapse Conformance Suite — fifteen checks, A through O, over one adapter.

WHY A SECOND MODULE AND NOT A SIXTH COLUMN IN THE HARNESS
---------------------------------------------------------
`harness.py` judges an adapter FIXTURE BY FIXTURE: it replays every payload and reports six
verdicts per payload. That shape is right for what it does and wrong for what §17 asks for.
A conformance claim is a statement about an ADAPTER — "this adapter is deterministic", "this
adapter refuses malformed input" — and several of the nine new checks cannot be expressed per
fixture at all: G decodes one payload three times, H reads a directory the harness deliberately
cannot see, K decodes twice through two fresh instances, N feeds bytes no fixture contains.

So the harness stays the engine for A–F and is not rewritten. This module composes it: it calls
`harness.run` once, folds its per-fixture verdicts into six adapter-level ones, and implements
G–O beside them. `harness.py`'s own JSON gains exactly one key (`check_letters`) and its text
output is untouched, because `cdm-harness --json` has consumers and this is an addition to a
published surface rather than a re-keying of it.

THE ONE RULE THIS MODULE EXISTS TO KEEP
---------------------------------------
A check that did not run is SKIP, never PASS (ARCHITECTURE.md §4.7, §3.6 rule 5). Every SKIP
here carries the reason it was inapplicable, and every check entry carries
`declared_inapplicable` — the second half of the pair §3.6 rule 5 requires the eligibility layer
to read. An adapter is not credited for a rung nobody climbed, and it is not blocked by one that
does not exist for it (§3.6 rule 4): the difference between those two is the whole model, and it
is a boolean in the report rather than a judgement in a reader's head.

WHAT IS DELIBERATELY NOT ASSERTED, AND WHY
------------------------------------------
Two rules that read well in a specification are not sound as written against an INJECTED FROZEN
CLOCK, and stating that here is cheaper than a reader rediscovering it from a green report:

1. "a timestamp equal to the frozen clock came from `now()`" is false in this tree — `cat048`'s
   `fspec_longer_than_necessary` fixture carries I048/140 = 22500.0 s = 06:15:00 exactly, which
   IS the frozen instant and IS a source time. J therefore tests the property §27 actually
   forbids, by DIFFERENTIAL: decode the payload under a second, different clock and see whether
   the timestamp moves. One that moves came from `now()`; §27 permits that only where the object
   says so, and every one in this tree does (`payload.observed_at_basis`).
2. `observed_at <= received_at` compares a scenario's source time against a TEST PARAMETER when
   the clock is frozen, and three adapters' fixtures legitimately observe after 06:15. The
   comparison is made only where `received_at` is not the injected instant, and the number of
   objects exempted is reported rather than silently dropped.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as _dt
import json
import pathlib
import sys
import time
import uuid
from typing import Any

from synapse_cdm import harness, lossless, times, version
from synapse_cdm.adapter import Adapter, load_adapter, packaged_fixtures, roster
from synapse_cdm.manifest import UnknownFields
from synapse_cdm.models import CDMBase
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION

PASS, FAIL, SKIP = harness.PASS, harness.FAIL, harness.SKIP

#: §40's four, spelled as `conformance.py:151–157` and `harness.py:99` spell them, so a caller who
#: knows one tool's codes is not surprised by this one's.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

#: The subdirectory H reads. A SUBDIRECTORY and not a naming convention, because
#: `harness.py:343` selects "immediate children of the directory that are FILES" — so every
#: payload in here is invisible to A–F by construction rather than by an exclusion somebody has
#: to remember to keep in step.
MALFORMED_DIR = "malformed"

#: §21's bound on one refusal. A malformed payload that has not been refused in five seconds has
#: not been refused; the check measures wall clock around the call and does not kill the thread,
#: because a parser that hangs is a finding to report and not a process to police.
DEFAULT_TIMEOUT_S = 5.0

#: F2.5. Every offset for a fixture under this size, evenly spaced up to this many for anything
#: larger. Stated in the report — a truncation sweep whose density is invisible is a number
#: nobody can reproduce.
DEFAULT_OFFSET_CAP = 4096

#: The four exception classes that are a CRASH rather than a refusal (F2.2). Everything else,
#: including a bare `Exception`, is a safe rejection with its class recorded. A declared
#: `SourceError` hierarchy is Part 2 and is written up as a limitation rather than assumed.
CRASH_CLASSES = (SystemExit, KeyboardInterrupt, MemoryError, RecursionError)

#: The CDM's own identity fields. `source.external_id` is deliberately NOT here: it is the
#: SOURCE's identifier, it is frequently a uuid4 drawn by somebody else, and asserting uuid5 over
#: it would fail three adapters for carrying their sources' identifiers faithfully.
IDENTITY_FIELDS = ("entity_id", "event_id", "track_id", "object_id")

#: Keys whose subtrees hold PARKED SOURCE VALUES rather than CDM fields. J does not walk into
#: them: a source timestamp parked verbatim in `attributes` is evidence that nothing was dropped,
#: and holding it to the CDM's serialisation rule would punish the adapter for keeping it.
PARKED = ("attributes", "payload", "source_extras")

_EPOCH = "1970-01-01T00:00:00.000Z"
_TOP_SENTINEL = "soifunknowntopsentinel"
_NESTED_SENTINEL = "soifunknownnestedsentinel"


@dataclasses.dataclass(frozen=True)
class Check:
    """One row of §18's table. `harness_key` is set for A–F and None for G–O."""

    letter: str
    name: str
    harness_key: str | None = None


#: §17's fifteen, in §17's order, with §18's spelling of each name. The letters are the
#: SUITE's namespace and are not the SC-OES tool's (ARCHITECTURE.md §8): a consumer merging two
#: reports finds these under `checks` and those under `dimensions`.
CHECKS: tuple[Check, ...] = (
    Check("A", "translate", "translate"),
    Check("B", "schema", "schema"),
    Check("C", "provenance", "provenance"),
    Check("D", "lossless", "lossless"),
    Check("E", "roundtrip", "roundtrip"),
    Check("F", "golden", "golden"),
    Check("G", "deterministic"),
    Check("H", "malformed-input"),
    Check("I", "unknown-preservation"),
    Check("J", "temporal"),
    Check("K", "identity"),
    Check("L", "version"),
    Check("M", "streaming"),
    Check("N", "parser robustness"),
    Check("O", "resource limits"),
)
CHECK_LETTERS: tuple[str, ...] = tuple(c.letter for c in CHECKS)
BY_LETTER: dict[str, Check] = {c.letter: c for c in CHECKS}

#: §3.6, step 2, as data. L0 is absent because it "requires no check — it requires a document",
#: and L5 is absent because its requirement is not a list: it is every check APPLICABLE to this
#: adapter, which is only knowable from the run. L6 is never computed here (§3.3).
LEVEL_REQUIREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("L1", ("A",)),
    ("L2", ("A", "B")),
    ("L3", ("A", "B", "C")),
    ("L4", ("A", "B", "C", "E")),
)


def _verdict(verdict: str, *, reason: str | None = None, declared: bool = False,
             **details: Any) -> dict:
    """One check entry. `declared_inapplicable` is on EVERY entry, not just the SKIPs.

    §3.6 rule 5 requires the report to carry the pair (verdict, which declaration made it
    inapplicable) so that the eligibility computation can be a separate layer that reads it. A
    flag present only on SKIPs would make its absence mean two things.
    """
    entry: dict[str, Any] = {"verdict": verdict, "declared_inapplicable": bool(declared)}
    if reason:
        entry["reason"] = reason
    entry["details"] = details
    return entry


def canonical(objects: list[dict]) -> str:
    """ARCHITECTURE.md §6.2's one serialisation, quoted there and written once here.

    WHY G COMPARES THESE STRINGS AND DOES NOT HASH THEM — A COLLISION, RECORDED RATHER THAN
    RESOLVED IN PASSING
    --------------------------------------------------------------------------------------
    ARCHITECTURE.md §4.4 says "P2's determinism check parses one fixture repeatedly,
    canonicalises, serialises, HASHES and compares", and §6.2 fixes the hash as sha256 over these
    bytes. `tests/test_cdm_boundary.py:74` forbids every module under `synapse_cdm/` from
    importing `hashlib`, with a reason of its own — signing belongs to the ledger, which holds the
    keys and is audited, and a digest is a signature's raw material. The two are both in the tree
    and this is the round that makes them meet.

    Neither is edited here. G compares the canonical serialisations DIRECTLY, which decides §20's
    question — "all hashes MUST match" — strictly more strongly than comparing digests of them
    would: two different serialisations cannot compare equal as strings, and two different
    serialisations CAN in principle share a digest. Nothing is weakened and no hash is quoted, so
    §6.2's rule about the form a quoted hash takes is not engaged.

    What is owed to a person is the ruling, not this workaround: P4's evidence records are
    specified to CARRY a hash, and a record that quotes one has to compute one. That decision —
    a narrow, reasoned exemption in the boundary gate, or a hash computed outside the package —
    belongs to whoever rules on P4, and it is written up in this round's report rather than taken
    here.
    """
    return json.dumps(objects, sort_keys=True, indent=2) + "\n"


def _dump(objects: list[CDMBase]) -> list[dict]:
    return [obj.model_dump(mode="json") for obj in objects]


def _fixtures(directory: pathlib.Path) -> list[pathlib.Path]:
    """`harness.py:343`'s three predicates, applied to the same directory it applies them to."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.name != "README.md")


def _fresh(adapter: Adapter, clock: times.Clock) -> Adapter:
    """A NEW instance of the same class under a stated clock, carrying nothing from the last one.

    K's whole question is whether identity is derived or remembered, and reusing the instance
    would let an adapter answer it out of a cache.
    """
    return type(adapter)(clock=clock, synthetic=adapter._synthetic)


def _walk(node: Any, path: str = "") -> Any:
    """Every leaf of the CDM's own structure, skipping the parked-source subtrees."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in PARKED:
                continue
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def _leaf_key(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("[")[0]


def _fold(report: dict, letter: str, key: str) -> dict:
    """A–F: one adapter-level verdict from the harness's per-fixture ones.

    FAIL if any fixture failed the check; else PASS if any fixture passed it; else SKIP, carrying
    the harness's own reasons. The order matters and is the conservative one — an adapter with
    one failing fixture is not credited for the ten that passed.
    """
    verdicts = [result["checks"].get(key, "-") for result in report["results"]]
    counts = {v: verdicts.count(v) for v in (PASS, FAIL, SKIP)}
    reasons = sorted({problem for result in report["results"]
                      for problem in result["problems"] if problem.startswith(f"{key}:")})
    details = {"fixtures": len(verdicts), **{k.lower(): v for k, v in counts.items()},
               "problems": reasons[:8]}
    if counts[FAIL]:
        return _verdict(FAIL, reason=(reasons[0] if reasons else None), **details)
    if counts[PASS]:
        return _verdict(PASS, **details)
    return _verdict(SKIP, reason=(reasons[0] if reasons else
                                  "every fixture reported SKIP for this check"), **details)


def _roundtrip_declaration(adapter: Adapter) -> tuple[bool, str]:
    """Is E's SKIP a DECLARED inapplicability (§3.6 rule 4) or an absence of evidence (rule 6)?

    Declared exactly once: an ingest-only adapter has no egress direction, which is §3.6's own
    standing example. The other SKIP the harness produces — `from_cdm` returned non-JSON bytes
    the structural comparison cannot read (`harness.py:246`) — is NOT a declared inapplicability.
    It is the tool saying it could not measure, and rule 6 blocks the rung on exactly that. Each
    bidirectional adapter ships its own byte-exact round-trip test in `tests/` (its manifest names
    it), and that evidence lives outside this suite: it is why one DECLARES L4 while the suite
    computes a lower eligibility, and the two numbers being different is the model working rather
    than a contradiction.
    """
    if adapter.direction == "ingest":
        return True, ("the adapter declares `direction: ingest`; there is no egress direction "
                      "for information to be lost in, so the check is inapplicable rather than "
                      "unrun (ARCHITECTURE.md §3.6 rule 4)")
    return False, ""


def check_deterministic(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                        clock: times.Clock, repeats: int = 3) -> dict:
    """G, §20: parse, canonicalise, serialise, hash, compare. Applicable to every adapter."""
    compared: dict[str, list[str]] = {}
    undecodable = []
    for name, raw in payloads:
        renderings = []
        for _ in range(repeats):
            try:
                renderings.append(canonical(_dump(_fresh(adapter, clock).to_cdm(raw))))
            except Exception as e:                             # noqa: BLE001 - A's verdict, not G's
                undecodable.append(f"{name}: {type(e).__name__}")
                break
        else:
            compared[name] = renderings
    unstable = {name: len(set(rs)) for name, rs in compared.items() if len(set(rs)) != 1}
    details = {"fixtures_compared": len(compared), "repeats": repeats,
               "undecodable": undecodable[:8], "serialisation": "ARCHITECTURE.md §6.2",
               "bytes_compared": sum(len(rs[0].encode("utf-8")) for rs in compared.values()),
               "unstable": unstable}
    if unstable:
        return _verdict(FAIL, reason=f"{len(unstable)} fixture(s) serialised differently across "
                                     f"{repeats} decodes under one frozen clock", **details)
    if not compared:
        return _verdict(SKIP, reason="no fixture decoded, so nothing could be compared; see "
                                     "check A", **details)
    return _verdict(PASS, **details)


def check_malformed(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock,
                    timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """H, §21: every payload under `malformed/` must be REFUSED, and refused safely.

    "Safely" is F2.2: any exception except the four crash classes, inside the time bound, with no
    object returned. The class is recorded because "it raised" and "it raised a KeyError from
    three frames down" are different facts about a parser, and Part 2's declared `SourceError`
    hierarchy is the repair — a limitation here, not an assumption.

    The REFUSING LAYER is recorded too. A malformed JSON document is refused by the fixture
    loader (`harness.load_raw`) before the adapter is asked, because the loader is what parses
    JSON — that is a true and useful fact about the pipeline and it is not the parser being
    exercised, so the check requires at least one payload to be refused by the ADAPTER itself.
    """
    directory = fixtures / MALFORMED_DIR
    if not directory.is_dir():
        return _verdict(SKIP, reason="no malformed fixtures declared: "
                                     f"{directory} does not exist", declared=True,
                        directory=str(directory))
    payloads = _fixtures(directory)
    if not payloads:
        return _verdict(FAIL, reason=f"{directory} exists and is empty; a declared malformed set "
                                     "with nothing in it reads as a passed check over an empty "
                                     "set", directory=str(directory))
    refusals, accepted, crashed, slow = [], [], [], []
    for path in payloads:
        started = time.monotonic()
        layer, outcome = "adapter", None
        try:
            raw = harness.load_raw(path)
        except CRASH_CLASSES:
            raise
        except Exception as e:                                 # noqa: BLE001 - recorded, not raised
            layer, outcome = "loader", f"{type(e).__module__}.{type(e).__name__}"
        if outcome is None:
            try:
                objects = _fresh(adapter, clock).to_cdm(raw)
            except CRASH_CLASSES as e:
                crashed.append(f"{path.name}: {type(e).__name__}")
                continue
            except Exception as e:                             # noqa: BLE001 - the refusal itself
                outcome = f"{type(e).__module__}.{type(e).__name__}"
            else:
                accepted.append(f"{path.name}: returned {len(objects)} object(s)")
                continue
        elapsed = time.monotonic() - started
        if elapsed > timeout_s:
            slow.append(f"{path.name}: refused after {elapsed:.3f}s")
        refusals.append({"fixture": path.name, "refused_by": layer, "exception": outcome,
                         "seconds": round(elapsed, 4)})
    by_adapter = [r for r in refusals if r["refused_by"] == "adapter"]
    details = {"payloads": len(payloads), "refusals": refusals, "accepted": accepted,
               "crashed": crashed, "over_time_bound": slow, "timeout_s": timeout_s,
               "refused_by_adapter": len(by_adapter),
               "exception_classes": sorted({r["exception"] for r in refusals})}
    if accepted:
        return _verdict(FAIL, reason=f"{len(accepted)} malformed payload(s) were ACCEPTED: "
                                     f"{accepted[0]}", **details)
    if crashed:
        return _verdict(FAIL, reason=f"a malformed payload raised a crash class: {crashed[0]}",
                        **details)
    if slow:
        return _verdict(FAIL, reason=f"a refusal took longer than {timeout_s}s: {slow[0]}",
                        **details)
    if not by_adapter:
        return _verdict(FAIL, reason="every malformed payload was refused by the fixture loader "
                                     "and none reached the adapter, so the parser was never "
                                     "asked to refuse anything", **details)
    return _verdict(PASS, **details)


def _inject(document: dict) -> tuple[dict, bool]:
    """One unknown scalar at the top level and one nested, into a copy."""
    payload = copy.deepcopy(document)
    payload["__soif_unknown_top"] = _TOP_SENTINEL
    target = None
    for value in payload.values():
        if isinstance(value, dict):
            target = value
            break
    if target is None:
        for value in payload.values():
            if isinstance(value, list):
                nested = [v for v in value if isinstance(v, dict)]
                if nested:
                    target = nested[0]
                    break
    if target is not None:
        target["__soif_unknown_nested"] = _NESTED_SENTINEL
    return payload, target is not None


def check_unknown_fields(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock) -> dict:
    """I: inject an unknown scalar the adapter has never seen and look for it in the output.

    The check READS THE DECLARATION rather than deciding applicability itself
    (`capabilities.unknown_fields`), because whether a format has a carrier for a field nobody
    defined is a fact about the format and not something a probe can establish: a probe that
    finds nothing has found either a format with no carrier or an adapter that drops what it
    carries, and those are opposite verdicts.

    Presence is `lossless._present_forms` — the same harvest check D uses — so "preserved" means
    what it means everywhere else in this repository.
    """
    declared = adapter.metadata.capabilities.unknown_fields
    if declared is UnknownFields.NONE:
        return _verdict(SKIP, reason="format has no unknown-field carrier: the adapter declares "
                                     "`capabilities.unknown_fields: none` — "
                        + adapter.metadata.capabilities.unknown_fields_basis,
                        declared=True, declaration="capabilities.unknown_fields")
    documents = [p for p in _fixtures(fixtures) if p.suffix.lower() == ".json"]
    missing, probed, no_nested = [], 0, 0
    for path in documents:
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            continue
        payload, nested = _inject(document)
        if not nested:
            no_nested += 1
        try:
            forms = lossless._present_forms(_dump(_fresh(adapter, clock).to_cdm(payload)))
        except Exception as e:                                 # noqa: BLE001 - reported, not raised
            missing.append(f"{path.name}: to_cdm raised {type(e).__name__} on a payload carrying "
                           f"one extra key: {e}")
            continue
        probed += 1
        if _TOP_SENTINEL not in forms:
            missing.append(f"{path.name}: the top-level unknown field was dropped")
        if nested and _NESTED_SENTINEL not in forms:
            missing.append(f"{path.name}: the nested unknown field was dropped")
    details = {"documents_probed": probed, "documents_without_a_nested_object": no_nested,
               "declaration": "preserved", "dropped": missing[:8]}
    if not documents:
        return _verdict(SKIP, reason="the adapter declares `unknown_fields: preserved` but ships "
                                     "no dict-form fixture to inject into; a bytes fixture has "
                                     "no generic carrier for an injected key", **details)
    if missing:
        return _verdict(FAIL, reason=missing[0], **details)
    return _verdict(PASS, **details)


def check_temporal(adapter: Adapter, payloads: list[tuple[str, Any]], *, clock: times.Clock,
                   frozen_at: _dt.datetime) -> dict:
    """J, §27. Three hard rules, one differential rule, one comparison that is not made.

    See this module's docstring for why the equality-to-the-clock proxy is not used and why the
    ordering comparison is conditional. The differential rule is the one that carries §27: a
    timestamp that MOVES when the injected clock moves came from `now()`, and §27 forbids an
    unknown time becoming `now()` — silently. Every one in this tree says so in the object
    itself, at `payload.observed_at_basis`, so the rule is testable rather than aspirational.

    `valid_from` / `valid_to` are OUTSIDE the differential rule and reported as a count instead.
    They are the entity's validity window, not the observation instant §27 speaks about, and
    temporal validity is the primitive P3 owes (ARCHITECTURE.md §9). Reporting the count keeps
    the fact visible; asserting on it here would rule a question this round was not given.
    """
    alternative = frozen_at + _dt.timedelta(days=2, hours=5, minutes=45)
    frozen_text = times.render(frozen_at)
    malformed, epochs, undeclared, ordering = [], [], [], []
    exempted_ordering = 0
    validity_tracks_clock = 0
    stamps = 0
    for name, raw in payloads:
        try:
            here = _dump(_fresh(adapter, clock).to_cdm(raw))
            there = _dump(_fresh(adapter, times.frozen_clock(alternative)).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not J's
            continue
        for index, obj in enumerate(here):
            other = there[index] if index < len(there) else {}
            carrier = {**(obj.get("payload") or {}), **(obj.get("attributes") or {})}
            moved = {path for path, value in _walk(other)}
            other_values = dict(_walk(other))
            for path, value in _walk(obj):
                if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
                    continue
                key = _leaf_key(path)
                if not (key.endswith("_at") or key.endswith("_from") or key.endswith("_to")):
                    continue
                stamps += 1
                if not times.TIMESTAMP_RE.match(value):
                    malformed.append(f"{name}: {path} = {value!r} is not RFC 3339 UTC with "
                                     "exactly three decimals and a trailing Z")
                if value == _EPOCH:
                    epochs.append(f"{name}: {path} = {value!r}; §27 forbids an unknown time "
                                  "becoming 1970-01-01")
                if key == "received_at" or path not in moved:
                    continue
                if other_values.get(path) == value:
                    continue
                if key in ("valid_from", "valid_to"):
                    validity_tracks_clock += 1
                    continue
                if not carrier.get(f"{key}_basis"):
                    undeclared.append(
                        f"{name}: {path} moved with the injected clock, so it came from "
                        f"now(), and the object declares no `{key}_basis` for it (§27)")
            observed, received = obj.get("observed_at"), obj.get("received_at")
            if isinstance(observed, str) and isinstance(received, str):
                if received == frozen_text:
                    exempted_ordering += 1
                elif observed > received:
                    ordering.append(f"{name}: observed_at {observed} is after received_at "
                                    f"{received}")
    details = {"timestamps": stamps, "alternative_clock": times.render(alternative),
               "ordering_exempted_frozen_receipt": exempted_ordering,
               "validity_window_tracks_the_clock": validity_tracks_clock,
               "problems": (malformed + epochs + undeclared + ordering)[:8]}
    if malformed or epochs or undeclared or ordering:
        return _verdict(FAIL, reason=(malformed + epochs + undeclared + ordering)[0], **details)
    if not stamps:
        return _verdict(SKIP, reason="the adapter emitted no CDM timestamp to judge", **details)
    return _verdict(PASS, **details)


def check_identity(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                   clock: times.Clock) -> dict:
    """K, Rule 3: derived identity is stable, and it is DERIVED.

    Two fresh instances, same configuration, same payload: every `entity_id`, `event_id`,
    `track_id` and `object_id` must be equal. And each must be a uuid5 — `ids.derive` is uuid5
    under a fixed namespace (`ids.py:28–41`), so a value that is not one was drawn rather than
    derived, whatever it looks like.
    """
    unstable, undrawn = [], []
    identifiers = 0
    for name, raw in payloads:
        try:
            first = _dump(_fresh(adapter, clock).to_cdm(raw))
            second = _dump(_fresh(adapter, clock).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not K's
            continue
        for index, obj in enumerate(first):
            twin = second[index] if index < len(second) else {}
            for path, value in _walk(obj):
                if _leaf_key(path) not in IDENTITY_FIELDS or not isinstance(value, str):
                    continue
                identifiers += 1
                if dict(_walk(twin)).get(path) != value:
                    unstable.append(f"{name}: {path} differs between two decodes of one payload")
                try:
                    if uuid.UUID(value).version != 5:
                        undrawn.append(f"{name}: {path} = {value} is a uuid"
                                       f"{uuid.UUID(value).version}, not the uuid5 `ids.derive` "
                                       "produces")
                except ValueError:
                    undrawn.append(f"{name}: {path} = {value!r} is not a UUID at all")
    details = {"identifiers": identifiers, "fields": list(IDENTITY_FIELDS),
               "problems": (unstable + undrawn)[:8]}
    if unstable or undrawn:
        return _verdict(FAIL, reason=(unstable + undrawn)[0], **details)
    if not identifiers:
        return _verdict(SKIP, reason="the adapter emitted no CDM identifier to judge", **details)
    return _verdict(PASS, **details)


def check_version(adapter: Adapter, payloads: list[tuple[str, Any]], *, clock: times.Clock,
                  supported: str) -> dict:
    """L: what the objects say they are written to, against what this package and this manifest
    say they support. Three statements that can disagree, checked as three."""
    wrong, incompatible, outside = [], [], []
    objects = 0
    major = supported.split(".", 1)[0]
    for name, raw in payloads:
        try:
            dumped = _dump(_fresh(adapter, clock).to_cdm(raw))
        except Exception:                                      # noqa: BLE001 - A's verdict, not L's
            continue
        for obj in dumped:
            written = obj.get("schema_version")
            if not isinstance(written, str):
                continue
            objects += 1
            if written != SCHEMA_VERSION:
                wrong.append(f"{name}: schema_version {written!r} is not this package's "
                             f"{SCHEMA_VERSION!r}")
            if not version.compatible(written, SCHEMA_VERSION):
                incompatible.append(f"{name}: version.compatible({written!r}, "
                                    f"{SCHEMA_VERSION!r}) is false")
            if written.split(".", 1)[0] != major:
                outside.append(f"{name}: schema_version {written!r} is outside the manifest's "
                               f"declared `cdm.supported` {supported!r}")
    details = {"objects": objects, "schema_version": SCHEMA_VERSION, "cdm_supported": supported,
               "problems": (wrong + incompatible + outside)[:8]}
    if wrong or incompatible or outside:
        return _verdict(FAIL, reason=(wrong + incompatible + outside)[0], **details)
    if not objects:
        return _verdict(SKIP, reason="the adapter emitted no object to judge", **details)
    return _verdict(PASS, **details)


def check_streaming(adapter: Adapter) -> dict:
    """M: SKIP unless the adapter declares a streaming capability.

    No adapter in this repository declares one and `Capabilities` has no field for it at manifest
    schema 1.0.0, so the absence is a closed model's declaration rather than an omission — which
    is why this is a DECLARED inapplicability and does not block a rung.
    """
    return _verdict(SKIP, reason="the adapter declares no streaming capability; `Capabilities` "
                                 "carries no `streaming` field at manifest schema "
                                 f"{version.MANIFEST_SCHEMA_VERSION}, so no adapter can declare "
                                 "one and the check has nothing to feed in two chunks",
                    declared=True, declaration="capabilities (no streaming field)")


def check_parser_robustness(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock,
                            offset_cap: int = DEFAULT_OFFSET_CAP,
                            timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """N, F2.5: truncate a byte fixture at every offset (evenly spaced above the cap) and require
    raise-not-crash.

    A truncated payload that DECODES is not a failure. Some formats are self-delimiting and a
    prefix of a valid payload is a valid shorter payload; requiring a refusal would be requiring
    a parser to reject something well-formed. What must not happen is a crash class or a hang,
    and those are what this measures.
    """
    byte_fixtures = [p for p in _fixtures(fixtures) if p.suffix.lower() != ".json"]
    if not byte_fixtures:
        return _verdict(SKIP, reason="not a byte stream: every fixture this adapter ships is a "
                                     "parsed dict, so there is nothing to truncate",
                        declared=True, declaration="the adapter's fixture set")
    crashed, slow = [], []
    attempts = 0
    decoded = 0
    for path in byte_fixtures:
        payload = path.read_bytes()
        size = len(payload)
        if size < 2:
            continue
        if size - 1 <= offset_cap:
            offsets = range(1, size)
        else:
            step = (size - 1) / offset_cap
            offsets = sorted({max(1, int(1 + index * step)) for index in range(offset_cap)})
        for offset in offsets:
            attempts += 1
            started = time.monotonic()
            try:
                _fresh(adapter, clock).to_cdm(payload[:offset])
                decoded += 1
            except CRASH_CLASSES as e:
                crashed.append(f"{path.name}[:{offset}]: {type(e).__name__}")
            except Exception:                                  # noqa: BLE001 - the refusal itself
                pass
            elapsed = time.monotonic() - started
            if elapsed > timeout_s:
                slow.append(f"{path.name}[:{offset}]: {elapsed:.3f}s")
    details = {"byte_fixtures": len(byte_fixtures), "offsets_tried": attempts,
               "offset_cap_per_fixture": offset_cap, "decoded_without_raising": decoded,
               "crashed": crashed[:8], "over_time_bound": slow[:8], "timeout_s": timeout_s}
    if crashed:
        return _verdict(FAIL, reason=f"a truncated payload raised a crash class: {crashed[0]}",
                        **details)
    if slow:
        return _verdict(FAIL, reason=f"a truncated payload took longer than {timeout_s}s to "
                                     f"refuse: {slow[0]}", **details)
    return _verdict(PASS, **details)


def check_resource_limits(adapter: Adapter, payloads: list[tuple[str, Any]], *,
                          clock: times.Clock) -> dict:
    """O: live only where `capabilities.limits.max_input_bytes` is declared (F2.3 → P5).

    The SKIP is a DECLARED inapplicability and not an omission, because `Limits` refuses an
    absent bound that carries no reason (`manifest.py:156`): every one of the fourteen states in
    its own manifest why it enforces none, and that sentence is what this quotes.
    """
    limits = adapter.metadata.capabilities.limits
    if limits.max_input_bytes is None:
        return _verdict(SKIP, reason="no limit declared: "
                        + limits.absent_because["max_input_bytes"],
                        declared=True, declaration="capabilities.limits.absent_because")
    if not payloads:
        return _verdict(SKIP, reason="no fixture to repeat up to the declared bound",
                        max_input_bytes=limits.max_input_bytes)
    seed = next((raw for _, raw in payloads if isinstance(raw, (bytes, bytearray))), None)
    if seed is None:
        return _verdict(SKIP, reason="the declared bound is a byte count and this adapter ships "
                                     "no byte fixture to repeat", declared=False,
                        max_input_bytes=limits.max_input_bytes)
    bound = limits.max_input_bytes
    oversized = (bytes(seed) * (bound // max(1, len(seed)) + 2))[:bound + 1]
    try:
        objects = _fresh(adapter, clock).to_cdm(oversized)
    except CRASH_CLASSES as e:
        return _verdict(FAIL, reason=f"an oversized payload raised a crash class: "
                                     f"{type(e).__name__}", max_input_bytes=bound)
    except Exception as e:                                     # noqa: BLE001 - the refusal itself
        return _verdict(PASS, max_input_bytes=bound, bytes_fed=len(oversized),
                        refusal=f"{type(e).__module__}.{type(e).__name__}")
    return _verdict(FAIL, reason=f"{len(oversized)} bytes is one more than the declared "
                                 f"max_input_bytes {bound} and the adapter accepted it, "
                                 f"returning {len(objects)} object(s)", max_input_bytes=bound)


def eligible_level(checks: dict[str, dict]) -> str:
    """ARCHITECTURE.md §3.6, steps 2–7, and nothing else.

    Rule 3 satisfies a requirement with PASS. Rule 4 lets a SKIP with a declared inapplicability
    through. Rule 6 blocks on FAIL and on an undeclared SKIP, and blocks every rung above. L5 is
    "every check APPLICABLE to this adapter". L0 needs a document rather than a check, so it is
    what remains when L1 is blocked; L6 is never computed here (rule 7).
    """
    def satisfied(letter: str) -> bool:
        entry = checks[letter]
        if entry["verdict"] == PASS:
            return True
        return entry["verdict"] == SKIP and entry["declared_inapplicable"]

    reached = "L0"
    for level, required in LEVEL_REQUIREMENTS:
        if not all(satisfied(letter) for letter in required):
            return reached
        reached = level
    if all(satisfied(letter) for letter in CHECK_LETTERS):
        return "L5"
    return reached


def run(adapter: Adapter, fixtures: pathlib.Path, *, clock: times.Clock | None = None,
        frozen_at: _dt.datetime | None = None, schema_dir: pathlib.Path | None = None,
        offset_cap: int = DEFAULT_OFFSET_CAP, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Every check, once, over one adapter. Raises `harness.NoFixturesFound` on a bad invocation."""
    frozen_at = frozen_at or times.FROZEN_NOW
    clock = clock or times.frozen_clock(frozen_at)
    base = harness.run(adapter, fixtures, schema_dir=schema_dir)
    payloads = [(path.name, harness.load_raw(path)) for path in _fixtures(fixtures)]

    checks: dict[str, dict] = {}
    for check in CHECKS:
        if check.harness_key is not None:
            entry = _fold(base, check.letter, check.harness_key)
            if check.letter == "E" and entry["verdict"] == SKIP:
                declared, reason = _roundtrip_declaration(adapter)
                entry["declared_inapplicable"] = declared
                entry["reason"] = reason or entry.get(
                    "reason", "the harness could not compare the emitted form structurally")
            checks[check.letter] = entry
    checks["G"] = check_deterministic(adapter, payloads, clock=clock)
    checks["H"] = check_malformed(adapter, fixtures, clock=clock, timeout_s=timeout_s)
    checks["I"] = check_unknown_fields(adapter, fixtures, clock=clock)
    checks["J"] = check_temporal(adapter, payloads, clock=clock, frozen_at=frozen_at)
    checks["K"] = check_identity(adapter, payloads, clock=clock)
    checks["L"] = check_version(adapter, payloads, clock=clock,
                                supported=f"{version.parse(SCHEMA_VERSION)[0]}.x")
    checks["M"] = check_streaming(adapter)
    checks["N"] = check_parser_robustness(adapter, fixtures, clock=clock, offset_cap=offset_cap,
                                          timeout_s=timeout_s)
    checks["O"] = check_resource_limits(adapter, payloads, clock=clock)

    failed = [letter for letter in CHECK_LETTERS if checks[letter]["verdict"] == FAIL]
    return {
        "adapter": {"id": adapter.metadata.id, "name": adapter.name,
                    "adapter_version": adapter.metadata.adapter_version,
                    "direction": adapter.direction, "system": adapter.system,
                    "declared_maturity": adapter.metadata.maturity.level.value,
                    "fixtures": str(fixtures)},
        "checks": {letter: checks[letter] for letter in CHECK_LETTERS},
        "result": "NON-CONFORMANT" if failed else "CONFORMANT",
        "maturity_eligible": eligible_level(checks),
        "generated_with": {"package": PACKAGE_VERSION, "schema": SCHEMA_VERSION,
                           "adapter_api": version.ADAPTER_API_VERSION},
    }


def exit_status(report: dict, required: tuple[str, ...] = ()) -> int:
    """§19: a required check that FAILs or SKIPs makes the INVOCATION unsuccessful.

    `conformance.py:754`'s idiom exactly, one namespace over: nothing here rewrites a verdict.
    `--require M` against an adapter that declares no streaming leaves `M = SKIP` in the report
    and returns non-zero, because collapsing the first into the second would put the caller's
    command line into the conformance record.
    """
    for letter in (required or CHECK_LETTERS):
        if report["checks"][letter]["verdict"] == FAIL:
            return EXIT_FAILED
    for letter in required:
        if report["checks"][letter]["verdict"] == SKIP:
            return EXIT_FAILED
    return EXIT_OK


def render_report(report: dict) -> str:
    """§18's layout exactly, then the reasons §17 requires a SKIP to carry.

    §18 fixes the block down to `MATURITY ELIGIBLE:`. It does not forbid saying why a check was
    inapplicable, and §17 requires it ("the report says WHY it was inapplicable"), so the reasons
    follow the block rather than being interleaved with it — the fixed shape stays parseable and
    the obligation is met.
    """
    lines = ["Synapse Conformance Suite", f"Adapter: {report['adapter']['id']}", ""]
    for check in CHECKS:
        entry = report["checks"][check.letter]
        lines.append(f"{check.letter} {check.name}".ljust(28) + entry["verdict"])
    lines += ["", f"RESULT: {report['result']}",
              f"MATURITY ELIGIBLE: {report['maturity_eligible']}"]
    reasons = [(c, report["checks"][c.letter]) for c in CHECKS
               if report["checks"][c.letter]["verdict"] != PASS]
    if reasons:
        lines += ["", "why, for every check that is not PASS "
                      "(a SKIP is never a PASS — ARCHITECTURE.md §4.7):"]
        for check, entry in reasons:
            declared = " [declared inapplicable]" if entry["declared_inapplicable"] else ""
            lines.append(f"  {check.letter} {entry['verdict']}{declared}  "
                         f"{entry.get('reason', '(no reason recorded)')}")
    return "\n".join(lines)


def render_roster(adapters: dict[str, type[Adapter]]) -> str:
    """`synapse conformance list`: the roster with what a conformance caller needs from it."""
    if not adapters:
        return ("no adapters are registered. synapse_cdm.adapters failed to import — this is a "
                "broken installation rather than an empty inventory")
    width = max(len(name) for name in adapters)
    lines = [f"{len(adapters)} adapters registered. Run one with "
             f"`synapse conformance run --adapter <name>`.", "",
             f"{'name'.ljust(width)}  {'version'.ljust(7)}  {'direction'.ljust(13)}  "
             f"{'maturity'.ljust(8)}  {'claim'.ljust(11)}  unknown-fields",
             "-" * (width + 2 + 7 + 2 + 13 + 2 + 8 + 2 + 11 + 2 + 14)]
    for name, cls in adapters.items():
        metadata = cls.metadata
        lines.append(f"{name.ljust(width)}  {cls.version.ljust(7)}  "
                     f"{cls.direction.ljust(13)}  {metadata.maturity.level.value.ljust(8)}  "
                     f"{metadata.claim_status.value.ljust(11)}  "
                     f"{metadata.capabilities.unknown_fields.value}")
    lines += ["", "The maturity column is what the adapter DECLARES. What the suite computes "
                  "from a run is `MATURITY ELIGIBLE`, and the two are different statements: one "
                  "is a claim about evidence, the other is this repository's evidence today."]
    return "\n".join(lines)


def _required(value: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    letters = tuple(part.strip().upper() for part in value.split(",") if part.strip())
    unknown = [letter for letter in letters if letter not in BY_LETTER]
    if unknown:
        parser.error(f"--require names {unknown}, which are not checks. The checks are "
                     f"{','.join(CHECK_LETTERS)} (see `synapse conformance list`)")
    return letters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    conformance = commands.add_parser("conformance", help="the Synapse Conformance Suite")
    actions = conformance.add_subparsers(dest="action")

    run_parser = actions.add_parser("run", help="run every check over one adapter")
    run_parser.add_argument("--adapter", required=True,
                            help="registered name (pntmap) or module:ClassName")
    run_parser.add_argument("--fixtures", type=pathlib.Path, default=None,
                            help="directory of payloads. Omitted, the fixtures that came with "
                                 "the installed package are used")
    run_parser.add_argument("--schemas", type=pathlib.Path, default=None,
                            help="validate against the published schemas in this directory")
    run_parser.add_argument("--format", default="text", choices=("text", "json"),
                            help="report shape (default text)")
    run_parser.add_argument("--require", default=None,
                            help="comma-separated letters that MUST pass; a FAIL or a SKIP among "
                                 "them exits non-zero (§19)")
    run_parser.add_argument("--now", default=None,
                            help="freeze received_at at this RFC 3339 instant "
                                 f"(default {times.render(times.FROZEN_NOW)})")
    run_parser.add_argument("--synthetic", default="true", choices=("true", "false"))
    run_parser.add_argument("--offset-cap", type=int, default=DEFAULT_OFFSET_CAP,
                            help=f"check N's truncation offsets per fixture (default "
                                 f"{DEFAULT_OFFSET_CAP}, F2.5)")
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                            help=f"seconds one refusal may take (default {DEFAULT_TIMEOUT_S})")

    actions.add_parser("list", help="the registered adapters, with declared maturity")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "conformance" or getattr(args, "action", None) is None:
        parser.error("usage: synapse conformance run --adapter <name> | synapse conformance list")
    if args.action == "list":
        print(render_roster(roster()))
        return EXIT_OK

    required = _required(args.require, parser) if args.require else ()
    frozen = times.parse(args.now) if args.now else times.FROZEN_NOW
    try:
        adapter_class = load_adapter(args.adapter)
    except LookupError as e:
        print(f"synapse conformance: {e}", file=sys.stderr)
        return EXIT_USAGE
    adapter = adapter_class(clock=times.frozen_clock(frozen), synthetic=args.synthetic == "true")

    fixtures = args.fixtures
    if fixtures is None:
        if not adapter_class.__module__.startswith("synapse_cdm.adapters."):
            print(f"synapse conformance: --fixtures is required for {args.adapter!r}: "
                  f"{adapter_class.__module__}.{adapter_class.__qualname__} is not one of the "
                  "adapters this package ships, so the package has no fixtures for it and will "
                  "not guess at a directory", file=sys.stderr)
            return EXIT_USAGE
        fixtures = packaged_fixtures(adapter_class)

    try:
        report = run(adapter, fixtures, clock=times.frozen_clock(frozen), frozen_at=frozen,
                     schema_dir=args.schemas, offset_cap=args.offset_cap,
                     timeout_s=args.timeout)
    except (harness.NoFixturesFound, harness.NoSchemasFound) as e:
        print(f"synapse conformance: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(report, indent=2, sort_keys=True) if args.format == "json"
          else render_report(report))
    return exit_status(report, required)


if __name__ == "__main__":
    raise SystemExit(main())
